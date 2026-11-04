"""
#278: search params are data on every runner path, never SQL text.

HybridRunner falls back to PostgresRunner when a view is missing or the
batch read fails, so PostgresRunner's builder is reachable from /analytics
too. Asserted against HAPI Postgres, not the generated SQL text.
"""

import pytest

pytestmark = pytest.mark.requires_services

from app.clients.hapi_db_client import close_hapi_db_client, create_hapi_db_client
from app.sql_on_fhir.errors import UnsupportedSearchParamError
from app.sql_on_fhir.runner.hybrid_runner import HybridRunner
from app.sql_on_fhir.runner.postgres_runner import PostgresRunner
from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager

INJECTION = "x' OR '1'='1"


@pytest.fixture
async def db_client():
    client = await create_hapi_db_client()
    yield client
    await close_hapi_db_client()


@pytest.fixture
def patient_view():
    return ViewDefinitionManager().load("patient_simple")


@pytest.mark.asyncio
@pytest.mark.parametrize("param", ["family", "gender", "_id", "birthdate"])
async def test_postgres_runner_treats_a_quote_as_data(db_client, patient_view, param):
    runner = PostgresRunner(db_client, enable_cache=False)

    assert await runner.execute_count(patient_view, search_params={param: INJECTION}) == 0


@pytest.mark.asyncio
async def test_postgres_runner_rejects_an_unknown_key(db_client, patient_view):
    # The old catch-all pasted the key into a JSONB path: ->>'{key}'.
    runner = PostgresRunner(db_client, enable_cache=False)

    with pytest.raises(UnsupportedSearchParamError):
        await runner.execute_count(patient_view, search_params={"gender' OR '1'='1": "x"})


@pytest.mark.asyncio
async def test_postgres_runner_select_binds_values_and_limit(db_client, patient_view):
    runner = PostgresRunner(db_client, enable_cache=False)

    rows = await runner.execute(patient_view, search_params={"gender": "female"}, max_resources=3)

    assert len(rows) == 3
    assert {r["gender"] for r in rows} == {"female"}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["execute", "execute_count"])
async def test_hybrid_runner_does_not_fall_back_on_an_unsupported_param(
    db_client, patient_view, method
):
    # A client error must surface, not retry on the PostgresRunner path.
    runner = HybridRunner(db_client, enable_cache=False)

    with pytest.raises(UnsupportedSearchParamError):
        await getattr(runner, method)(patient_view, search_params={"not-a-param": "x"})
    assert runner._postgres_queries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/analytics/count", "/analytics/execute"])
async def test_analytics_rejects_an_unsupported_param_as_a_client_error(route):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api import analytics

    app = FastAPI()
    app.include_router(analytics.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            route,
            json={"view_name": "patient_simple", "search_params": {"1=1 OR gender": "x"}},
        )

    assert response.status_code == 400
    assert "1=1 OR gender" not in response.text, "don't echo client input"


@pytest.mark.asyncio
async def test_hybrid_status_filter_on_a_sqlonfhir_table_still_counts(db_client):
    # The sqlonfhir views are tables, so HybridRunner routes them to PostgresRunner;
    # `status` must still work there, as it did through the old catch-all.
    runner = HybridRunner(db_client, enable_cache=False)
    view_def = ViewDefinitionManager().load("procedure_history")
    rows = await db_client.execute_query(
        "SELECT COUNT(DISTINCT id) AS count FROM sqlonfhir.procedure_history WHERE status = $1",
        ["completed"],
    )

    count = await runner.execute_count(view_def, search_params={"status": "completed"})

    assert count == rows[0]["count"] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [{}, {"eq": "male"}])
async def test_a_dict_value_without_a_range_is_rejected_not_dropped(db_client, value):
    from app.sql_on_fhir.runner.materialized_view_runner import MaterializedViewRunner

    runner = MaterializedViewRunner(db_client)
    view_def = ViewDefinitionManager().load("patient_demographics")

    with pytest.raises(UnsupportedSearchParamError):
        await runner.execute_count(view_def, search_params={"gender": value})


@pytest.mark.asyncio
async def test_like_wildcards_in_a_value_are_literal(db_client):
    from app.sql_on_fhir.runner.materialized_view_runner import MaterializedViewRunner

    runner = MaterializedViewRunner(db_client)
    view_def = ViewDefinitionManager().load("patient_demographics")

    assert await runner.execute_count(view_def, search_params={"given": "%"}) == 0
    assert await runner.execute_count(view_def, search_params={"given": "_"}) == 0
