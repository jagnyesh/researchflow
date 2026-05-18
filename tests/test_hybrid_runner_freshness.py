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
