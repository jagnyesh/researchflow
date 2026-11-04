"""
#277: coded search params match exactly on the batch layer.

`ILIKE '%male%'` matched `female`, so `gender=male` counted every patient.
Asserted against the real views, not the generated SQL text.
"""

import pytest

pytestmark = pytest.mark.requires_services

from app.clients.hapi_db_client import close_hapi_db_client, create_hapi_db_client
from app.sql_on_fhir.runner.materialized_view_runner import MaterializedViewRunner
from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager


@pytest.fixture
async def db_client():
    client = await create_hapi_db_client()
    yield client
    await close_hapi_db_client()


async def _direct_count(db_client, view_name: str, column: str, value: str) -> int:
    rows = await db_client.execute_query(
        f"SELECT COUNT(*) AS count FROM sqlonfhir.{view_name} WHERE {column} = $1", [value]
    )
    return rows[0]["count"]


@pytest.mark.asyncio
@pytest.mark.parametrize("gender", ["male", "female"])
async def test_gender_count_matches_exact_gender(db_client, gender):
    runner = MaterializedViewRunner(db_client)
    view_def = ViewDefinitionManager().load("patient_demographics")

    expected = await _direct_count(db_client, "patient_demographics", "gender", gender)
    assert expected > 0, "vacuous: no patients of this gender in the corpus"

    assert await runner.execute_count(view_def, search_params={"gender": gender}) == expected


@pytest.mark.asyncio
async def test_gender_match_ignores_case_like_the_speed_layer(db_client):
    # speed_layer_runner lowercases both sides; the batch read must agree.
    runner = MaterializedViewRunner(db_client)
    view_def = ViewDefinitionManager().load("patient_demographics")

    expected = await _direct_count(db_client, "patient_demographics", "gender", "male")

    assert await runner.execute_count(view_def, search_params={"gender": "Male"}) == expected
