"""#111: medication_requests materializes its medication columns.

The custom transpiler emits NULL for `medication.ofType(CodeableConcept)...`,
so medication_code / _display / _text were NULL in all 20,116 rows and
"patients on metformin" counted 0. The view now builds on the sqlonfhir
runner (ADR 0026), which handles ofType.

The live check reads HAPI (:5433) only, in a read-only transaction, and
evaluates the view in memory exactly as scripts/materialize_views.py does;
it writes nothing.
"""

import json
import socket
from pathlib import Path

import pytest

from app.sql_on_fhir.runner.backend_dispatcher import select_backend
from app.sql_on_fhir.runner.mv_health_check import load_oracle_query

VIEW = (
    Path(__file__).resolve().parents[1]
    / "app/sql_on_fhir/view_definitions/medication_requests.json"
)


def _view():
    return json.loads(VIEW.read_text())


def _hapi_reachable():
    try:
        with socket.create_connection(("localhost", 5433), timeout=0.5):
            return True
    except OSError:
        return False


def test_medication_requests_builds_on_sqlonfhir():
    assert select_backend(_view()) == "sqlonfhir"


def test_medication_requests_has_a_row_count_oracle():
    oracle = load_oracle_query("medication_requests")

    assert oracle and "MedicationRequest" in oracle
    assert "'active', 'completed', 'on-hold'" in oracle  # the view-def's WHERE


@pytest.mark.asyncio
@pytest.mark.requires_services
@pytest.mark.skipif(not _hapi_reachable(), reason="HAPI Postgres (:5433) not running")
async def test_coded_medications_materialize_their_code_display_and_text():
    import asyncpg
    import sqlonfhir

    from app.sql_on_fhir.runner.hapi_db_resource_reader import fetch_fhir_resources_for_view

    conn = await asyncpg.connect("postgresql://hapi:hapi@localhost:5433/hapi")
    try:
        await conn.execute("SET default_transaction_read_only = on")
        resources = await fetch_fhir_resources_for_view(conn, _view())
        [oracle] = await conn.fetch(load_oracle_query("medication_requests"))
    finally:
        await conn.close()

    rows = sqlonfhir.evaluate(resources, _view())
    coded = [
        r for r in resources if "medicationCodeableConcept" in r
    ]  # the rest reference a Medication resource
    filled = {
        c: sum(1 for row in rows if row[c] is not None)
        for c in ("medication_code", "medication_display", "medication_text")
    }

    assert len(rows) == oracle[0]
    assert coded, "precondition: the corpus has coded medications"
    assert filled == {c: len(coded) for c in filled}, filled
