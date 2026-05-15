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
# Test 2 (cycle 3 tracer bullet) — end-to-end condition_diagnoses via sqlonfhir
# ---------------------------------------------------------------------------

# Expected oracle count from tests/fixtures/mv_row_count_oracles.sql at sprint
# start (2026-05-15). The 1% gate measures actual count against this anchor.
# See the oracle SQL file's comment block for the WHERE-clause replication
# and the data observation explaining the status distribution.
#
# Distribution: 'active' = 3,582 + 'resolved' = 11,250 = 14,832. The other
# three OR-set statuses ('recurrence', 'relapse', 'remission') don't appear
# in current Synthea data. All 14,832 stored Conditions pass the view-def
# WHERE clause for today's corpus.
CONDITION_DIAGNOSES_ORACLE_AT_SPRINT_START = 14832
ORACLE_TOLERANCE_PCT = 1.0


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
async def test_condition_diagnoses_materialized_via_sqlonfhir_end_to_end():
    """Sprint 6.4 cycle 3 tracer bullet — end-to-end condition_diagnoses.

    Full path:
      1. Load condition_diagnoses.json view-def (must declare
         runner_hint: "sqlonfhir" — set in cycle 3)
      2. ViewMaterializer.materialize_view() dispatches to
         _materialize_via_sqlonfhir()
      3. fetch_fhir_resources_for_view() reads Conditions from HAPI :5433
         (hfj_resource + hfj_res_ver JOIN; fhir_id merged into JSON)
      4. sqlonfhir.evaluate() produces rows
      5. CREATE TABLE sqlonfhir.condition_diagnoses + TRUNCATE + INSERT
      6. Row count matches the oracle SQL in
         tests/fixtures/mv_row_count_oracles.sql within 1%

    Sanity assertion (covers the fhir_id merge requirement surfaced during
    exploration): every materialized row must have non-NULL id. Without
    the merge in fetch_fhir_resources_for_view(), the JSON stored by HAPI
    lacks `id` and the view-def's `id` path resolves to NULL, breaking
    the UNIQUE INDEX assertion.
    """
    if not await _hapi_reachable():
        pytest.skip("requires_hapi: HAPI Postgres :5433 not reachable")

    db_url = os.environ.get("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi").replace(
        "+asyncpg", ""
    )
    materializer = ViewMaterializer(db_url)

    # Load condition_diagnoses view-def — must declare runner_hint
    view_def_path = (
        Path(__file__).resolve().parents[1]
        / "app/sql_on_fhir/view_definitions/condition_diagnoses.json"
    )
    with open(view_def_path) as f:
        view_def = json.load(f)
    assert view_def.get("runner_hint") == "sqlonfhir", (
        'condition_diagnoses.json must declare `runner_hint: "sqlonfhir"` for '
        "cycle 3. If this assertion fails, the view-def hasn't been migrated yet."
    )

    conn = await asyncpg.connect(db_url)
    try:
        await materializer.create_schema(conn)
        result = await materializer.materialize_view(
            conn, "condition_diagnoses", view_def, "Condition"
        )
        assert result, "materialize_view should return truthy on success"

        # Row count vs oracle anchored at sprint start (gate #1, 1% tolerance)
        actual = await conn.fetchval("SELECT count(*) FROM sqlonfhir.condition_diagnoses")
        delta_pct = (
            abs(actual - CONDITION_DIAGNOSES_ORACLE_AT_SPRINT_START)
            / CONDITION_DIAGNOSES_ORACLE_AT_SPRINT_START
            * 100
        )
        assert delta_pct < ORACLE_TOLERANCE_PCT, (
            f"condition_diagnoses row count {actual} differs from oracle "
            f"{CONDITION_DIAGNOSES_ORACLE_AT_SPRINT_START} by {delta_pct:.2f}% "
            f"(> {ORACLE_TOLERANCE_PCT}% tolerance). See "
            f"tests/fixtures/mv_row_count_oracles.sql for the oracle's WHERE "
            f"clause and data observations."
        )

        # Sanity: every row has non-NULL id (verifies fhir_id merge worked).
        # Without the merge, view-def's id path resolves to NULL and UNIQUE
        # INDEX creation fails earlier — but check explicitly so the test
        # surfaces the exact failure mode.
        null_id_count = await conn.fetchval(
            "SELECT count(*) FROM sqlonfhir.condition_diagnoses WHERE id IS NULL"
        )
        assert null_id_count == 0, (
            f"{null_id_count} rows have NULL id. The fhir_id merge in "
            f"fetch_fhir_resources_for_view() may not have applied."
        )
    finally:
        await conn.close()
