"""Sprint 6.4 cycle 7 — Custom-path MV regression check (gate #2).

The cycles 1-3 added backend dispatching that routes view-defs marked
with `runner_hint: "sqlonfhir"` through the new sqlonfhir backend. The
4 custom-path MVs (patient_simple, patient_demographics, condition_simple,
medication_requests) have NO runner_hint and must continue to materialize
correctly via the legacy custom-FHIRPath-transpiler path.

Sprint 6.4 #40 gate #2 requires verification that the dispatch refactor
didn't regress the custom path. This file is that verification — one
parametrized end-to-end test per custom-path MV.

Gates exercised:
  - #2: 4 custom-path MVs continue to materialize with no regression
  - #5: dispatch routing (unmarked view-def → custom path)

The pattern matches tests/test_sqlonfhir_integration.py but anchors
against raw resource counts (no view-def WHERE clauses on these 4 MVs;
1 row per stored resource of the matching resource_type).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg
import pytest
from dotenv import load_dotenv

# scripts/ isn't a package; add it to sys.path
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from materialize_views import ViewMaterializer  # noqa: E402

load_dotenv()


# Anchored at sprint start 2026-05-15 against HAPI :5433 Synthea load.
# None of these 4 view-defs has a WHERE clause, so the expected row count
# equals the raw count of non-deleted resources of the matching type. See
# the resource-count probe in cycle 7's commit message for measurement.
CUSTOM_PATH_MV_ANCHORS = {
    "patient_simple": {
        "resource_type": "Patient",
        "expected_count": 366,
    },
    "patient_demographics": {
        "resource_type": "Patient",
        "expected_count": 366,
    },
    "condition_simple": {
        "resource_type": "Condition",
        "expected_count": 14832,
    },
    "medication_requests": {
        "resource_type": "MedicationRequest",
        "expected_count": 20116,
    },
}

# 1% tolerance — same as gate #1 in test_sqlonfhir_integration.py
TOLERANCE_PCT = 1.0


async def _hapi_reachable() -> bool:
    """Connection probe for the requires_hapi gate. Matches the helper in
    test_sqlonfhir_integration.py.
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
@pytest.mark.parametrize("view_name", list(CUSTOM_PATH_MV_ANCHORS.keys()))
async def test_custom_path_mv_materializes_without_regression(view_name):
    """Sprint 6.4 cycle 7 / gate #2 — the 4 custom-path MVs continue to
    materialize correctly after the cycles 1-3 backend dispatcher landed.

    Each MV:
      1. Has its view-def loaded from app/sql_on_fhir/view_definitions/
      2. Has NO runner_hint field (default = custom path)
      3. Gets materialized via ViewMaterializer.materialize_view, which
         must dispatch to _materialize_via_custom() (NOT _via_sqlonfhir)
      4. Lands a row count within 1% of the anchor (gate #2 tolerance)
    """
    if not await _hapi_reachable():
        pytest.skip("requires_hapi: HAPI Postgres :5433 not reachable")

    db_url = os.environ.get("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi").replace(
        "+asyncpg", ""
    )

    view_def_path = (
        Path(__file__).resolve().parents[1] / f"app/sql_on_fhir/view_definitions/{view_name}.json"
    )
    with open(view_def_path) as f:
        view_def = json.load(f)

    # Pre-condition: this test only protects the custom path; if the
    # view-def has been migrated to sqlonfhir, the wrong test file is
    # exercising it.
    assert view_def.get("runner_hint") != "sqlonfhir", (
        f"{view_name}.json declares `runner_hint: sqlonfhir`. This file "
        f"only protects custom-path MVs. Move this view to "
        f"tests/test_sqlonfhir_integration.py's MV_ORACLES dict."
    )

    spec = CUSTOM_PATH_MV_ANCHORS[view_name]
    expected_count = spec["expected_count"]
    resource_type = spec["resource_type"]

    materializer = ViewMaterializer(db_url)
    conn = await asyncpg.connect(db_url)
    try:
        await materializer.create_schema(conn)
        result = await materializer.materialize_view(conn, view_name, view_def, resource_type)
        assert result, f"materialize_view({view_name}) should return truthy on success"

        actual = await conn.fetchval(f"SELECT count(*) FROM sqlonfhir.{view_name}")
        delta_pct = abs(actual - expected_count) / expected_count * 100
        assert delta_pct < TOLERANCE_PCT, (
            f"{view_name} row count {actual} differs from anchor "
            f"{expected_count} by {delta_pct:.2f}% (> {TOLERANCE_PCT}% "
            f"tolerance). Custom-path regression — backend dispatcher "
            f"may be incorrectly routing this view to sqlonfhir, or the "
            f"custom transpiler has a new bug."
        )
    finally:
        await conn.close()
