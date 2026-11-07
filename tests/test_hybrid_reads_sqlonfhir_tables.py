"""#263: HybridRunner serves every view from its sqlonfhir batch table.

The sqlonfhir backend stores condition_diagnoses / observation_labs /
procedure_history as plain tables (ADR 0026), which a pg_matviews-only check
missed; HybridRunner then fell back to the custom transpiler, which can't
express their FHIRPath (ofType, where($this in ...)) and returned 0. The
fallback now refuses a view definition it can't express.

Against the real HAPI Postgres (:5433), read-only: execute_count records no
metric and touches no Redis.
"""

import json
import socket
from pathlib import Path

import pytest

from app.sql_on_fhir.errors import UnsupportedViewDefinitionError
from app.sql_on_fhir.runner.hybrid_runner import HybridRunner

VIEWS_DIR = Path(__file__).resolve().parents[1] / "app" / "sql_on_fhir" / "view_definitions"
VIEWS = sorted(p.stem for p in VIEWS_DIR.glob("*.json"))


def _view(name):
    return json.loads((VIEWS_DIR / f"{name}.json").read_text())


def _hapi_reachable():
    try:
        with socket.create_connection(("localhost", 5433), timeout=0.5):
            return True
    except OSError:
        return False


def _runner(db_client):
    from app.cache.redis_client import RedisClient

    # Never connected: execute_count doesn't use the speed layer.
    return HybridRunner(db_client, redis_client=RedisClient(), enable_cache=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", VIEWS)
@pytest.mark.requires_services
@pytest.mark.skipif(not _hapi_reachable(), reason="HAPI Postgres (:5433) not running")
async def test_every_view_counts_from_its_batch_table(db_client, name):
    assert len(VIEWS) == 7

    runner = _runner(db_client)
    count = await runner.execute_count(_view(name))

    [row] = await db_client.execute_query(f"SELECT count(*) AS n FROM sqlonfhir.{name}")
    assert count == row["n"]
    assert count > 0
    # Served by the batch table, not the transpiler fallback (procedure_history's
    # live fallback count happens to match, so the count alone can't show it).
    assert runner._postgres_runner is None


@pytest.mark.asyncio
@pytest.mark.requires_services
@pytest.mark.skipif(not _hapi_reachable(), reason="HAPI Postgres (:5433) not running")
async def test_the_fallback_refuses_a_view_it_cannot_express(db_client):
    # No batch table by this name, so HybridRunner falls back to the transpiler.
    view = dict(_view("condition_diagnoses"), name="condition_diagnoses_not_materialized")

    with pytest.raises(UnsupportedViewDefinitionError):
        await _runner(db_client).execute_count(view)


def test_the_batch_transpiler_stays_lenient():
    # scripts/materialize_views.py builds the custom-path views with the
    # default transpiler; it keeps emitting NULL for an unsupported function
    # (medication_requests has three) rather than failing the nightly build.
    from app.sql_on_fhir.query_builder import create_sql_query_builder
    from app.sql_on_fhir.transpiler import create_column_extractor, create_fhirpath_transpiler

    transpiler = create_fhirpath_transpiler()
    builder = create_sql_query_builder(transpiler, create_column_extractor(transpiler))

    assert builder.build_query(_view("medication_requests")).sql


def test_a_strict_transpiler_refuses_condition_diagnoses():
    from app.sql_on_fhir.query_builder import create_sql_query_builder
    from app.sql_on_fhir.transpiler import create_column_extractor, create_fhirpath_transpiler

    transpiler = create_fhirpath_transpiler(strict=True)
    builder = create_sql_query_builder(transpiler, create_column_extractor(transpiler))

    with pytest.raises(UnsupportedViewDefinitionError, match="ofType"):
        builder.build_query(_view("condition_diagnoses"))


def _strict_builder():
    from app.sql_on_fhir.query_builder import create_sql_query_builder
    from app.sql_on_fhir.transpiler import create_column_extractor, create_fhirpath_transpiler

    transpiler = create_fhirpath_transpiler(strict=True)
    return transpiler, create_sql_query_builder(transpiler, create_column_extractor(transpiler))


@pytest.mark.parametrize(
    "construct, call",
    [
        (
            "where-clause pattern",
            lambda t, b: t.transpile_where_predicate("name.given.matches('x')"),
        ),
        ("where condition", lambda t, b: t.transpile("telecom.where(rank > 1).value")),
        ("where clause", lambda t, b: t.transpile("name.where(")),
        (
            "unionAll",
            lambda t, b: b.build_query(
                {
                    "resource": "Patient",
                    "name": "u",
                    "select": [{"unionAll": [{"column": [{"name": "a", "path": "id"}]}]}],
                }
            ),
        ),
    ],
)
def test_each_lenient_site_refuses_in_strict_mode(construct, call):
    transpiler, builder = _strict_builder()

    with pytest.raises(UnsupportedViewDefinitionError, match=construct):
        call(transpiler, builder)
