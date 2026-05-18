"""Tests for scripts/drive_fhir_traffic.py — Sprint 6.5 Phase 1 (#68).

Integration tests against a real HAPI FHIR server at :8081 (per the project's
docker-compose mapping). Skipped when HAPI isn't reachable so CI without
service containers doesn't false-fail.

The `synthetic_t2dm_patient` fixture is the deterministic test-driver Sprint
6.5's later phases need: Phase 2A's HybridRunner integration tests, Phase 4's
gate script, and any future regression test wanting "add one t2dm patient,
assert downstream side-effect" all reuse it.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import httpx
import pytest

from scripts.drive_fhir_traffic import (
    COHORT_PRESETS,
    FHIR_SERVER,
    build_synthetic_bundle,
    write_one,
)


pytestmark = [pytest.mark.integration, pytest.mark.requires_hapi]


async def _hapi_reachable() -> bool:
    """Return True iff HAPI's `metadata` endpoint responds in <2s."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{FHIR_SERVER}/metadata")
            return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
async def skip_if_hapi_unreachable():
    """Skip the whole module if HAPI isn't up — CI without services."""
    if not await _hapi_reachable():
        pytest.skip(f"HAPI not reachable at {FHIR_SERVER}")


@pytest.fixture
async def synthetic_t2dm_patient() -> AsyncIterator[tuple[str, str, str]]:
    """Write one t2dm patient and yield (patient_id, condition_id, observation_id).
    DELETE all three on teardown so test runs don't accumulate state.

    Downstream Sprint 6.5 tests (HybridRunner integration, gate script,
    speed-layer-merge assertions) use this as their canonical 'something
    changed in HAPI' fixture so they don't each redefine the bundle shape.

    Cleanup matters: without DELETE, Sprint 6.4's
    `test_custom_path_mv_materializes_without_regression[patient_simple]`
    regression test fails because Synthea-anchored row counts shift. The
    gate (Phase 4) intentionally does NOT clean up — it's a one-shot
    empirical evidence run, not a unit test.
    """
    patient_id, condition_id, observation_id = await write_one("t2dm")
    try:
        yield patient_id, condition_id, observation_id
    finally:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Order: child resources before parent (HAPI rejects parent
            # deletion when references exist with default referential-
            # integrity policy). Observation + Condition reference
            # Patient, so they go first.
            for resource_type, resource_id in (
                ("Observation", observation_id),
                ("Condition", condition_id),
                ("Patient", patient_id),
            ):
                try:
                    await client.delete(f"{FHIR_SERVER}/{resource_type}/{resource_id}")
                except Exception:
                    # Cleanup is best-effort; CI failure here would mask the
                    # real test failure. The next test run will tolerate
                    # leaked state because integration tests are tolerant
                    # of monotonic HAPI growth.
                    pass


class TestBundleShape:
    """Build-side tests that don't touch HAPI — runnable without services."""

    def test_t2dm_preset_uses_snomed_44054006(self):
        """T2DM cohort must encode SNOMED 44054006 so condition_simple's
        snomed_code filter (Sprint 6.2 #21) can pick it up."""
        bundle = build_synthetic_bundle("t2dm")
        condition_entry = bundle["entry"][1]
        coding = condition_entry["resource"]["code"]["coding"][0]
        assert coding["system"] == "http://snomed.info/sct"
        assert coding["code"] == "44054006"

    def test_hypertension_preset_uses_snomed_38341003(self):
        """Same shape for hypertension preset — locks the contract."""
        bundle = build_synthetic_bundle("hypertension")
        condition_entry = bundle["entry"][1]
        coding = condition_entry["resource"]["code"]["coding"][0]
        assert coding["system"] == "http://snomed.info/sct"
        assert coding["code"] == "38341003"

    def test_bundle_uses_urn_fullurl_so_hapi_assigns_ids(self):
        """Inter-resource references must use urn:uuid: so HAPI rewrites
        them to its own ids on POST."""
        bundle = build_synthetic_bundle("t2dm")
        patient_full_url = bundle["entry"][0]["fullUrl"]
        condition_subject = bundle["entry"][1]["resource"]["subject"]["reference"]
        assert patient_full_url.startswith("urn:uuid:")
        assert condition_subject == patient_full_url

    def test_only_two_presets_registered(self):
        """If a third preset is added, the gate's hardcoded t2dm assumption
        and the dashboard's hardcoded view-name filter both need updating —
        this test forces an explicit code review at preset-add time."""
        assert set(COHORT_PRESETS.keys()) == {"t2dm", "hypertension"}


class TestWriteEndToEnd:
    """Live HAPI tests — verify the bundle actually lands and id triples
    come back. These reuse the `synthetic_t2dm_patient` fixture so cleanup
    happens deterministically; without that, each test would leak 3 resources
    and Sprint 6.4's Synthea-anchored regression tests would drift."""

    async def test_returns_three_valid_ids(self, synthetic_t2dm_patient):
        patient_id, condition_id, observation_id = synthetic_t2dm_patient
        assert patient_id and patient_id.isdigit(), f"bad patient_id: {patient_id!r}"
        assert condition_id and condition_id.isdigit(), f"bad condition_id: {condition_id!r}"
        assert (
            observation_id and observation_id.isdigit()
        ), f"bad observation_id: {observation_id!r}"

    async def test_written_patient_is_retrievable(self, synthetic_t2dm_patient):
        patient_id, _, _ = synthetic_t2dm_patient
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{FHIR_SERVER}/Patient/{patient_id}", timeout=5.0)
        assert r.status_code == 200
        body = r.json()
        assert body["resourceType"] == "Patient"
        assert body["gender"] == "male"
        assert body["birthDate"] == "1980-01-01"

    async def test_written_condition_is_linked_to_patient(self, synthetic_t2dm_patient):
        patient_id, condition_id, _ = synthetic_t2dm_patient
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{FHIR_SERVER}/Condition/{condition_id}", timeout=5.0)
        assert r.status_code == 200
        body = r.json()
        assert body["subject"]["reference"] == f"Patient/{patient_id}"
        coding = body["code"]["coding"][0]
        assert coding["code"] == "44054006"


class TestMVRefreshMetadata:
    """Verify scripts/materialize_views.py wrote refresh metadata to the
    sqlonfhir.mv_refresh_metadata table — Sprint 6.5 Phase 1 second half."""

    async def test_mv_refresh_metadata_has_entries_after_refresh(self, db_client):
        """After at least one materialize_views.py --refresh run, the
        metadata table should have one row per MV. This test assumes the
        operator (or a prior gate run) has refreshed at least once today.

        Uses the conftest db_client fixture rather than raw asyncpg.connect
        so the DSN-prefix handling stays consistent with HAPIDBClient
        (which strips postgresql+asyncpg:// → postgresql:// before
        connecting). Originally written with raw asyncpg.connect, this
        test failed when .env's HAPI_DB_URL was loaded into the shell
        because asyncpg can't parse the SQLAlchemy-flavored DSN.
        """
        async with db_client.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT view_name, MAX(refreshed_at) AS last_refresh, MAX(row_count) AS row_count
                FROM sqlonfhir.mv_refresh_metadata
                GROUP BY view_name
                ORDER BY view_name
                """
            )

        assert len(rows) > 0, (
            "sqlonfhir.mv_refresh_metadata is empty — run "
            "`python scripts/materialize_views.py --refresh` first"
        )
        # Each refreshed view should have a non-null refreshed_at and a
        # positive row_count (Synthea's data is non-empty).
        for row in rows:
            assert row["last_refresh"] is not None
            assert row["row_count"] > 0, f"view {row['view_name']} has row_count={row['row_count']}"
