"""Sprint 6.4 cycle 3 — sqlonfhir backend end-to-end integration.

The dispatch primitive (cycle 1) + ViewMaterializer integration (cycle 2)
now route view-defs to the sqlonfhir branch when `runner_hint: "sqlonfhir"`
is declared. Cycle 3 implements that branch: fetch FHIR resources from
HAPI Postgres :5433, evaluate via `sqlonfhir.evaluate()`, write rows to
`sqlonfhir.<view_name>` via CREATE TABLE + TRUNCATE + INSERT (NOT
CREATE MATERIALIZED VIEW — sqlonfhir produces rows, not SQL; the storage
asymmetry is documented in the Sprint 6.4 ADR).

This file covers:

  1. Minimal dispatch-routing test (retained from cycle 2 per Q2 refinement) —
     asserts ViewMaterializer.materialize_view() routes sqlonfhir-marked
     view-defs to _materialize_via_sqlonfhir() and unmarked view-defs to
     _materialize_via_custom(). Protects against future regression in
     routing logic.

  2. End-to-end integration test (cycle 3 tracer bullet) — full path against
     real HAPI Postgres :5433. Gated by @pytest.mark.requires_hapi so the
     test suite runs cleanly without HAPI; integration runs require it.

Sprint 6.4 #40 gates exercised by this file:
  - Gate #1 (row count within 1% of oracle anchored at sprint start) — for
    condition_diagnoses; observation_labs + procedure_history land in cycle 4
  - Gate #5 (dispatch plumbing) — the minimal routing test
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest
from dotenv import load_dotenv

# scripts/ isn't a package; add it to sys.path
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from materialize_views import ViewMaterializer  # noqa: E402

load_dotenv()


# ---------------------------------------------------------------------------
# Test 1 (Q2 retained) — minimal dispatch-routing test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_materialize_view_routes_sqlonfhir_marked_to_sqlonfhir_branch():
    """ViewMaterializer.materialize_view() dispatches on `runner_hint`.

    Sqlonfhir-marked view-def → _materialize_via_sqlonfhir() called.
    No real DB writes — we spy via AsyncMock; the assertion is which
    method was reached, not what happened inside it. This is the
    one routing-protection test that survives cycle 2 → cycle 3 redesign.
    """
    materializer = ViewMaterializer("postgresql://dummy")  # no connection
    materializer._materialize_via_sqlonfhir = AsyncMock(return_value=True)
    materializer._materialize_via_custom = AsyncMock(return_value=True)

    view_def = {
        "resourceType": "ViewDefinition",
        "resource": "Condition",
        "name": "test_view",
        "runner_hint": "sqlonfhir",
    }
    fake_conn = MagicMock()
    await materializer.materialize_view(fake_conn, "test_view", view_def, "Condition")

    materializer._materialize_via_sqlonfhir.assert_awaited_once()
    materializer._materialize_via_custom.assert_not_awaited()


@pytest.mark.asyncio
async def test_materialize_view_routes_unmarked_to_custom_branch():
    """Unmarked view-def → _materialize_via_custom() called.

    Backward compatibility for the 4 working MVs.
    """
    materializer = ViewMaterializer("postgresql://dummy")
    materializer._materialize_via_sqlonfhir = AsyncMock(return_value=True)
    materializer._materialize_via_custom = AsyncMock(return_value=True)

    view_def = {
        "resourceType": "ViewDefinition",
        "resource": "Patient",
        "name": "patient_simple",
        # no runner_hint field
    }
    fake_conn = MagicMock()
    await materializer.materialize_view(fake_conn, "patient_simple", view_def, "Patient")

    materializer._materialize_via_custom.assert_awaited_once()
    materializer._materialize_via_sqlonfhir.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests 2-4 (cycle 3 + cycle 4) — end-to-end MV materialization via sqlonfhir
# ---------------------------------------------------------------------------

# Expected oracle counts from tests/fixtures/mv_row_count_oracles.sql,
# anchored at sprint start (2026-05-15). The 1% gate measures actual count
# against these anchors. See the oracle SQL file's comment blocks for each
# view-def's WHERE-clause replication and data observations.
MV_ORACLES = {
    # condition_diagnoses (cycle 3): WHERE clause matches both 'active' and
    # 'resolved' in current Synthea data; all 14,832 stored Conditions pass.
    "condition_diagnoses": {
        "oracle_count": 14832,
        "resource_type": "Condition",
    },
    # observation_labs (cycle 4): laboratory category AND finalized status;
    # ~68.6% of 229,870 Observations qualify.
    "observation_labs": {
        "oracle_count": 157689,
        "resource_type": "Observation",
    },
    # procedure_history (cycle 4): Synthea only emits 'completed' status, so
    # the WHERE clause filter is effectively a no-op against current data.
    # The 3 forEachOrNull blocks preserve a row per Procedure when arrays
    # are empty (verified by Sprint 6.3 spike: 30/30 Procedures → 30 rows).
    "procedure_history": {
        "oracle_count": 66448,
        "resource_type": "Procedure",
    },
}

ORACLE_TOLERANCE_PCT = 1.0

# Per Sprint 6.4 #40 gate #3: observation_labs materialization ≤ 60s.
# Inherited from Sprint 6.3 spike C4 threshold. observation_labs is the
# load test because it has the largest input set (229k Observations).
OBSERVATION_LABS_MATERIALIZATION_BUDGET_S = 60.0


async def _hapi_reachable() -> bool:
    """Connection probe for the requires_hapi gate. Robust to local-dev
    (localhost:5433) and CI-docker sibling-container hostnames — uses the
    HAPI_DB_URL env var if set, falls back to localhost otherwise.
    """
    url = os.environ.get("HAPI_DB_URL", "").replace("+asyncpg", "")
    if not url:
        url = "postgresql://hapi:hapi@localhost:5433/hapi"
    try:
        conn = await asyncio.wait_for(asyncpg.connect(url), timeout=3.0)
        await conn.close()
        return True
    except Exception:
        return False


@pytest.mark.asyncio
@pytest.mark.requires_hapi
@pytest.mark.parametrize("view_name", list(MV_ORACLES.keys()))
async def test_mv_materialized_via_sqlonfhir_end_to_end(view_name):
    """Sprint 6.4 cycle 3 (condition_diagnoses) + cycle 4 (observation_labs,
    procedure_history) — end-to-end materialization via sqlonfhir.

    Full path per MV:
      1. Load <mv>.json view-def (must declare `runner_hint: "sqlonfhir"`)
      2. ViewMaterializer.materialize_view() dispatches to
         _materialize_via_sqlonfhir()
      3. fetch_fhir_resources_for_view() reads <resource> resources from
         HAPI :5433 (hfj_resource + hfj_res_ver JOIN; fhir_id merged into
         each parsed JSON dict)
      4. sqlonfhir.evaluate() produces rows in-memory
      5. CREATE TABLE sqlonfhir.<mv> + TRUNCATE + INSERT via executemany
      6. Row count matches oracle within 1% (gate #1)
      7. Every row has non-NULL id (fhir_id merge verification)

    For observation_labs additionally: gate #3 perf budget — total
    materialization wall-clock ≤ 60s. observation_labs has the largest
    input set (229k Observations) so it's the load test for the budget.
    """
    if not await _hapi_reachable():
        pytest.skip("requires_hapi: HAPI Postgres :5433 not reachable")

    db_url = os.environ.get("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi").replace(
        "+asyncpg", ""
    )
    materializer = ViewMaterializer(db_url)

    view_def_path = (
        Path(__file__).resolve().parents[1] / f"app/sql_on_fhir/view_definitions/{view_name}.json"
    )
    with open(view_def_path) as f:
        view_def = json.load(f)
    assert view_def.get("runner_hint") == "sqlonfhir", (
        f'{view_name}.json must declare `runner_hint: "sqlonfhir"` for the '
        "sqlonfhir backend path to be exercised. If this assertion fails, "
        "the view-def hasn't been migrated yet."
    )

    spec = MV_ORACLES[view_name]
    oracle_count = spec["oracle_count"]
    resource_type = spec["resource_type"]

    conn = await asyncpg.connect(db_url)
    try:
        await materializer.create_schema(conn)
        import time

        t0 = time.monotonic()
        result = await materializer.materialize_view(conn, view_name, view_def, resource_type)
        elapsed_s = time.monotonic() - t0
        assert result, f"materialize_view({view_name}) should return truthy on success"

        # Gate #3 — perf budget for observation_labs only (the load test)
        if view_name == "observation_labs":
            assert elapsed_s <= OBSERVATION_LABS_MATERIALIZATION_BUDGET_S, (
                f"observation_labs materialization took {elapsed_s:.1f}s, "
                f"exceeds gate #3 budget of {OBSERVATION_LABS_MATERIALIZATION_BUDGET_S:.0f}s. "
                f"Per Sprint 6.3 spike C4 threshold."
            )

        # Gate #1 — row count vs oracle anchored at sprint start (1% tolerance)
        actual = await conn.fetchval(f"SELECT count(*) FROM sqlonfhir.{view_name}")
        delta_pct = abs(actual - oracle_count) / oracle_count * 100
        assert delta_pct < ORACLE_TOLERANCE_PCT, (
            f"{view_name} row count {actual} differs from oracle {oracle_count} "
            f"by {delta_pct:.2f}% (> {ORACLE_TOLERANCE_PCT}% tolerance). See "
            f"tests/fixtures/mv_row_count_oracles.sql for the oracle's WHERE "
            f"clause and data observations."
        )

        # Sanity: every row has non-NULL id (fhir_id merge verification)
        null_id_count = await conn.fetchval(
            f"SELECT count(*) FROM sqlonfhir.{view_name} WHERE id IS NULL"
        )
        assert null_id_count == 0, (
            f"{view_name}: {null_id_count} rows have NULL id. The fhir_id "
            f"merge in fetch_fhir_resources_for_view() may not have applied."
        )

        # Sprint 6.4 cycle 5 — verify post-write health check fired and
        # wrote a JSONL record. The check is wired into both
        # _materialize_via_custom() and _materialize_via_sqlonfhir(); for
        # the 3 sqlonfhir MVs that have oracles defined in
        # mv_row_count_oracles.sql, every successful materialize_view call
        # should append one record.
        from app.sql_on_fhir.runner.mv_health_check import DEFAULT_LOG_PATH

        assert (
            DEFAULT_LOG_PATH.exists()
        ), "mv_health.jsonl should be created after a successful materialize"
        # Read the last record for this view and assert it's well-formed
        last_record_for_view = None
        with open(DEFAULT_LOG_PATH) as f:
            for line in f:
                rec = json.loads(line.strip())
                if rec.get("view_name") == view_name:
                    last_record_for_view = rec
        assert (
            last_record_for_view is not None
        ), f"no health-check record for {view_name} in {DEFAULT_LOG_PATH}"
        # Status should be "ok" since the row count matches the oracle
        # (gate #1 already passed above; this verifies the health check
        # agrees and produced a structured record).
        assert last_record_for_view["status"] == "ok", (
            f"health-check status for {view_name} should be 'ok' "
            f"(actual matches oracle); got {last_record_for_view}"
        )
        assert last_record_for_view["delta_pct"] <= 5.0
        assert "ts" in last_record_for_view
        assert "git_commit" in last_record_for_view
    finally:
        await conn.close()
