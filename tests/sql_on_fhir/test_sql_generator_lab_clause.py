"""#80: a lab criterion queries sqlonfhir.observation_labs, not a raw `observation`.

The raw table doesn't exist in HAPI's schema, so any phenotype with a lab
criterion failed at execution. Executed through the production adapter.
"""

import pytest

pytestmark = pytest.mark.requires_services

from app.adapters.sql_on_fhir import SQLonFHIRAdapter
from app.utils.sql_generator import SQLGenerator
from tests.fixtures import RequirementsBuilder as RB

LAB = "Hemoglobin A1c"


async def _count(sql, params):
    rows = await SQLonFHIRAdapter().execute_sql(sql, params)
    return next(iter(rows[0].values()))


async def _patients_with_lab(term: str) -> int:
    rows = await SQLonFHIRAdapter().execute_sql(
        "SELECT COUNT(DISTINCT p.patient_id) AS n FROM sqlonfhir.patient_demographics p "
        "WHERE EXISTS (SELECT 1 FROM sqlonfhir.observation_labs o WHERE o.patient_id = p.patient_id "
        "AND (LOWER(o.code_text) LIKE LOWER(:t) OR LOWER(o.code_display) LIKE LOWER(:t)))",
        {"t": f"%{term}%"},
    )
    return rows[0]["n"]


@pytest.mark.asyncio
@pytest.mark.parametrize("include", [True, False])
async def test_lab_criterion_counts_patients_with_that_lab(include):
    criterion = RB.build_lab(LAB, term=LAB)
    requirements = RB.build_requirements(
        inclusion=[criterion] if include else [], exclusion=[] if include else [criterion]
    )
    sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        requirements, count_only=True
    )

    with_lab = await _patients_with_lab(LAB)
    total = await _count("SELECT COUNT(*) FROM sqlonfhir.patient_demographics", None)
    assert 0 < with_lab < total, "vacuous: the lab must split the corpus"

    assert await _count(sql, params) == (with_lab if include else total - with_lab)
