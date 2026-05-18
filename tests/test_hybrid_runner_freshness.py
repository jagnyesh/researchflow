"""Tests for FreshnessAnnotation enum + HybridRunner routing + metrics
emission + LangSmith tags.

Sprint 6.5 Phase 2A (#69). 8 TDD cycles, each one RED-GREEN-COMMIT. Each
test name maps 1:1 to the cycle name in issue #69's acceptance criteria.

These tests cover the core HybridRunner extension. Agent wiring is
Phase 2B (#70) — these tests do NOT exercise phenotype_agent or
extraction_agent. They drive HybridRunner directly via test fixtures.

Cycles 2-8 need real HAPI :5433 + Redis (the existing Sprint 6.2
speed-integration test pattern). Fixtures duplicated locally rather
than centralized in conftest.py to keep the blast radius of Phase 2A
work contained.
"""

from __future__ import annotations

import os

import pytest

from app.cache.redis_client import RedisClient
from app.clients.hapi_db_client import close_hapi_db_client, create_hapi_db_client
from app.sql_on_fhir.runner.freshness import FreshnessAnnotation
from app.sql_on_fhir.runner.hybrid_runner import HybridRunner
from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager


# ============================================================================
# Fixtures (Cycle 2+) — duplicated from
# tests/test_hybrid_runner_speed_integration.py with caching disabled for
# deterministic test runs. Cycles 1's enum test doesn't use these.
# ============================================================================


@pytest.fixture
async def db_client():
    """HAPI database client at :5433."""
    client = await create_hapi_db_client()
    yield client
    await close_hapi_db_client()


@pytest.fixture
async def redis_client():
    """Redis client for the speed layer, isolated DB to avoid prod data."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/1")
    client = RedisClient(redis_url=redis_url)
    await client.connect()
    await client.flush_all()
    yield client
    await client.flush_all()
    await client.disconnect()


@pytest.fixture
async def hybrid_runner(db_client, redis_client):
    """HybridRunner under test, caching disabled for determinism."""
    return HybridRunner(
        db_client=db_client,
        redis_client=redis_client,
        enable_cache=False,
    )


@pytest.fixture
def view_def_manager():
    return ViewDefinitionManager()


class TestFreshnessAnnotation:
    """Cycle 1: enum locks the three routing modes."""

    def test_freshness_annotation_enum_has_three_values(self):
        """Sprint 6.5 routes HybridRunner reads on FreshnessAnnotation.

        Three modes are the load-bearing architectural claim — they map
        to researcher-facing portals (EXPLORATORY ↔ :8501 Exploratory
        Portal, FORMAL_* ↔ :8502 Formal Portal) AND expose the
        pre/post-approval split inside the Formal Portal workflow.
        """
        values = {member.name for member in FreshnessAnnotation}
        assert values == {"EXPLORATORY", "FORMAL_DRAFT", "FORMAL_EXTRACTION"}


class TestHybridRunnerRouting:
    """Cycles 2-4: HybridRunner.execute() routes on FreshnessAnnotation."""

    pytestmark = pytest.mark.requires_services

    async def test_hybrid_runner_routes_exploratory_to_speed_merge(
        self, hybrid_runner, redis_client, view_def_manager
    ):
        """EXPLORATORY mode merges speed-layer rows into the result.

        Pre-load Redis with a synthetic Patient the batch MV cannot have
        (the id is freshly invented), call HybridRunner.execute with
        mode=EXPLORATORY, assert the synthetic Patient appears in the
        result. If the merge path didn't fire, the synthetic id is not
        in the result and the test fails.

        This is the behavior-through-public-interface assertion: nothing
        in the test pokes at HybridRunner internals or asserts which
        sub-runner got called. The observable signal is "did a row
        sourced from Redis make it through to the caller?"
        """
        synthetic_patient = {
            "resourceType": "Patient",
            "id": "speed-merge-cycle-2",
            "gender": "male",
            "birthDate": "1990-01-01",
            "name": [{"family": "SpeedMergeCycle2", "given": ["Synthetic"]}],
        }
        await redis_client.set_fhir_resource("Patient", synthetic_patient["id"], synthetic_patient)

        view_def = view_def_manager.load("patient_simple")
        assert view_def is not None, "patient_simple view-def must exist for this test"

        rows = await hybrid_runner.execute(
            view_definition=view_def,
            search_params={},
            max_resources=None,
            mode=FreshnessAnnotation.EXPLORATORY,
        )

        result_ids = {r.get("id") for r in rows if r.get("id")}
        assert "speed-merge-cycle-2" in result_ids, (
            f"EXPLORATORY mode failed to merge speed-layer row. "
            f"Expected 'speed-merge-cycle-2' in results; got {len(result_ids)} ids."
        )

    async def test_hybrid_runner_routes_formal_draft_to_speed_merge_with_metadata(
        self, hybrid_runner, redis_client, view_def_manager
    ):
        """FORMAL_DRAFT mode merges speed-layer rows AND exposes batch_anchor_ts.

        The pre-approval cohort-estimation step in the Formal Portal workflow
        needs BOTH:
          1. Fresh data (speed-layer merge, same as EXPLORATORY) so the
             researcher sees today's reality while iterating on criteria
          2. A citation anchor (batch_anchor_ts) so the same query can be
             traced back to the batch state at estimation time

        Observable through public interface via the result rows + the sibling
        getter HybridRunner.get_last_batch_anchor_ts() — same pattern as the
        existing get_last_executed_sql() at hybrid_runner.py:229. Test does
        NOT poke at HybridRunner internals; the getter is the contract.
        """
        from datetime import datetime

        synthetic_patient = {
            "resourceType": "Patient",
            "id": "formal-draft-cycle-3",
            "gender": "female",
            "birthDate": "1985-06-15",
            "name": [{"family": "FormalDraftCycle3", "given": ["Synthetic"]}],
        }
        await redis_client.set_fhir_resource("Patient", synthetic_patient["id"], synthetic_patient)

        view_def = view_def_manager.load("patient_simple")
        assert view_def is not None

        rows = await hybrid_runner.execute(
            view_definition=view_def,
            search_params={},
            max_resources=None,
            mode=FreshnessAnnotation.FORMAL_DRAFT,
        )

        # Speed-merge fired (same shape as EXPLORATORY for FORMAL_DRAFT)
        result_ids = {r.get("id") for r in rows if r.get("id")}
        assert "formal-draft-cycle-3" in result_ids, (
            f"FORMAL_DRAFT mode failed to merge speed-layer row. "
            f"Expected 'formal-draft-cycle-3' in results; got {len(result_ids)} ids."
        )

        # batch_anchor_ts is accessible via the sibling getter and points
        # to a real refresh event (mv_refresh_metadata seeded by Phase 1
        # for patient_simple; non-null datetime is the contract here, the
        # MAX-across-views assertion lands in Cycle 6).
        anchor = hybrid_runner.get_last_batch_anchor_ts()
        assert anchor is not None, (
            "FORMAL_DRAFT must populate batch_anchor_ts via "
            "get_last_batch_anchor_ts() — required for the citation anchor "
            "Phase 4's gate asserts on."
        )
        assert isinstance(
            anchor, datetime
        ), f"batch_anchor_ts should be a datetime; got {type(anchor).__name__}"

    async def test_hybrid_runner_routes_formal_extraction_to_batch_only(
        self, hybrid_runner, redis_client, view_def_manager
    ):
        """FORMAL_EXTRACTION mode skips speed-layer merge entirely.

        Post-approval extraction in the Formal Portal workflow needs the
        opposite of FORMAL_DRAFT: citable reproducibility, not freshness.
        Researcher approves a cohort *definition* (SQL/criteria), not a
        row-set. The row-set materializes at extraction time against the
        current BATCH state — speed-layer overlay is excluded so that
        re-running the same query (against the same batch state, anchored
        by batch_anchor_ts) is bit-identical.

        Observable contract: a Patient that exists ONLY in the speed
        layer (Redis pre-loaded, MV not refreshed since) must NOT appear
        in FORMAL_EXTRACTION result rows. The same id is verified absent.
        """
        from datetime import datetime

        synthetic_patient = {
            "resourceType": "Patient",
            "id": "formal-extraction-cycle-4",
            "gender": "male",
            "birthDate": "1975-11-22",
            "name": [{"family": "FormalExtractionCycle4", "given": ["Synthetic"]}],
        }
        await redis_client.set_fhir_resource("Patient", synthetic_patient["id"], synthetic_patient)

        view_def = view_def_manager.load("patient_simple")
        assert view_def is not None

        rows = await hybrid_runner.execute(
            view_definition=view_def,
            search_params={},
            max_resources=None,
            mode=FreshnessAnnotation.FORMAL_EXTRACTION,
        )

        # Speed-merge skipped — the synthetic id (Redis-only, not in MV)
        # must NOT appear in the result.
        result_ids = {r.get("id") for r in rows if r.get("id")}
        assert "formal-extraction-cycle-4" not in result_ids, (
            "FORMAL_EXTRACTION leaked a speed-layer-only row into result. "
            "The citability contract requires batch-only reads — re-running "
            "the same query against the same batch_anchor_ts must be "
            f"bit-identical. Got {len(result_ids)} ids including the "
            "synthetic one that should have been excluded."
        )

        # batch_anchor_ts is still populated — FORMAL_EXTRACTION needs it
        # MORE than FORMAL_DRAFT does (it's the citation anchor).
        anchor = hybrid_runner.get_last_batch_anchor_ts()
        assert anchor is not None, (
            "FORMAL_EXTRACTION must populate batch_anchor_ts — without it "
            "the result is not citable (no way to identify which batch "
            "state the extraction was anchored against)."
        )
        assert isinstance(anchor, datetime)
