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


@pytest.mark.asyncio
async def test_quote_bearing_value_is_data_not_sql(db_client):
    # #278: values used to be pasted into the SQL text, so a quote broke the query.
    runner = MaterializedViewRunner(db_client)
    view_def = ViewDefinitionManager().load("patient_demographics")

    assert await runner.execute_count(view_def, search_params={"family": "O'Brien"}) == 0
    assert (
        await runner.execute_count(view_def, search_params={"family": "x' OR '1'='1"}) == 0
    ), "a quote must not widen the filter"


@pytest.mark.asyncio
async def test_unmapped_key_is_rejected_not_used_as_a_column(db_client):
    from app.sql_on_fhir.errors import UnsupportedSearchParamError

    runner = MaterializedViewRunner(db_client)
    view_def = ViewDefinitionManager().load("patient_demographics")

    with pytest.raises(UnsupportedSearchParamError):
        await runner.execute_count(view_def, search_params={"1=1 OR gender": "x"})


@pytest.mark.asyncio
async def test_clinical_status_matches_exactly(db_client):
    # '%act%' matched 'active'; FHIR also has 'inactive', which '%active%' would match.
    runner = MaterializedViewRunner(db_client)
    view_def = ViewDefinitionManager().load("condition_simple")

    assert await runner.execute_count(view_def, search_params={"clinical-status": "act"}) == 0
    expected = await _direct_count(db_client, "condition_simple", "clinical_status", "active")
    assert (
        await runner.execute_count(view_def, search_params={"clinical-status": "active"})
        == expected
    )


@pytest.mark.asyncio
async def test_patient_reference_matches_one_patient_not_an_id_substring(db_client):
    runner = MaterializedViewRunner(db_client)
    view_def = ViewDefinitionManager().load("condition_simple")
    rows = await db_client.execute_query(
        "SELECT patient_id FROM sqlonfhir.condition_simple LIMIT 1"
    )
    patient_id = rows[0]["patient_id"]
    expected = await _direct_count(db_client, "condition_simple", "patient_id", patient_id)

    assert await runner.execute_count(view_def, search_params={"patient": patient_id}) == expected
    assert await runner.execute_count(view_def, search_params={"patient": patient_id[:-1]}) == 0


@pytest.mark.asyncio
async def test_list_of_genders_ignores_case(db_client):
    runner = MaterializedViewRunner(db_client)
    view_def = ViewDefinitionManager().load("patient_demographics")
    expected = await _direct_count(db_client, "patient_demographics", "gender", "male")

    assert await runner.execute_count(view_def, search_params={"gender": ["Male"]}) == expected


@pytest.mark.asyncio
async def test_select_with_limit_binds_and_filters(db_client):
    runner = MaterializedViewRunner(db_client)
    view_def = ViewDefinitionManager().load("patient_demographics")

    rows = await runner.execute(view_def, search_params={"gender": "female"}, max_resources=5)

    assert len(rows) == 5
    assert {r["gender"] for r in rows} == {"female"}
