"""Phenotype SQL for combined, excluded and data-element criteria, run live (#23).

Replaces the deleted string-shape suite (test_sql_generation_quality.py) for
the behaviors nothing else covered: exclusion criteria, several inclusion
criteria together, and the full (non-count) query. Each generated query runs
through the production adapter and is checked against hand-written SQL.
Time periods are not covered here: that path fails live today (#315).
"""

import pytest

pytestmark = pytest.mark.requires_services

from app.adapters.sql_on_fhir import SQLonFHIRAdapter
from app.utils.sql_generator import SQLGenerator
from tests.fixtures import RequirementsBuilder as RB


def _has(term: str) -> str:
    return (
        "EXISTS (SELECT 1 FROM sqlonfhir.condition_simple c WHERE c.patient_id = p.patient_id "
        f"AND (LOWER(c.code_text) LIKE '%{term}%' OR LOWER(c.icd10_display) LIKE '%{term}%' "
        f"OR LOWER(c.snomed_display) LIKE '%{term}%'))"
    )


async def _count(where: str) -> int:
    rows = await SQLonFHIRAdapter().execute_sql(
        f"SELECT COUNT(DISTINCT p.patient_id) AS n FROM sqlonfhir.patient_demographics p WHERE {where}"  # nosec B608 - test constants
    )
    return rows[0]["n"]


async def _generated_count(requirements) -> int:
    sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        requirements, count_only=True
    )
    rows = await SQLonFHIRAdapter().execute_sql(sql, params)
    return rows[0]["patient_count"]


@pytest.mark.asyncio
async def test_an_exclusion_removes_those_patients():
    requirements = RB.build_requirements(
        inclusion=[RB.build_condition("diabetes", term="diabetes")],
        exclusion=[RB.build_condition("hypertension", term="hypertension")],
    )
    expected = await _count(f"{_has('diabetes')} AND NOT {_has('hypertension')}")

    assert 0 < expected < await _count(_has("diabetes")), "the exclusion must bite"
    assert await _generated_count(requirements) == expected


@pytest.mark.asyncio
async def test_several_inclusion_criteria_all_apply():
    requirements = RB.build_requirements(
        inclusion=[
            RB.build_condition("diabetes", term="diabetes"),
            RB.build_condition("hypertension", term="hypertension"),
        ]
    )
    expected = await _count(f"{_has('diabetes')} AND {_has('hypertension')}")

    assert 0 < expected < await _count(_has("diabetes"))
    assert await _generated_count(requirements) == expected


@pytest.mark.asyncio
async def test_the_full_query_returns_one_row_per_cohort_patient_with_demographics():
    requirements = RB.build_requirements(
        inclusion=[RB.build_condition("diabetes", term="diabetes")],
        data_elements=["demographics"],
    )
    sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        requirements, count_only=False
    )

    rows = await SQLonFHIRAdapter().execute_sql(sql, params)

    assert len(rows) == len({r["patient_id"] for r in rows}) == await _count(_has("diabetes"))
    assert {"gender", "birth_date"} <= set(rows[0])
