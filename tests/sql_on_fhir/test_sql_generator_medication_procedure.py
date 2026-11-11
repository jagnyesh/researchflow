"""#310 (ADR 0036): medication and procedure criteria reach the phenotype SQL.

The generator used to drop both concept types silently, so the cohort counted
every patient the other criteria allowed. Each generated count runs through
the production adapter and is checked against a hand-written count over the
same view columns. The terms split both the local corpus and CI's seed.
"""

import pytest

pytestmark = pytest.mark.requires_services

from app.adapters.sql_on_fhir import SQLonFHIRAdapter
from app.utils.sql_generator import SQLGenerator
from tests.fixtures import RequirementsBuilder as RB

# concept type: view, columns the oracle matches, a term in the local corpus and CI's seed
KINDS = {
    "medication": ("medication_requests", ("medication_display", "medication_text"), "metformin"),
    "procedure": (
        "procedure_history",
        ("code_text", "snomed_display", "cpt_display"),
        "blood glucose",
    ),
}


async def _count(sql, params=None) -> int:
    rows = await SQLonFHIRAdapter().execute_sql(sql, params)
    return next(iter(rows[0].values()))


async def _patients_with(view, columns, term) -> int:
    match = " OR ".join(f"x.{col} ILIKE :t" for col in columns)
    return await _count(
        "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p "  # nosec B608 - test constants
        f"WHERE EXISTS (SELECT 1 FROM sqlonfhir.{view} x WHERE x.patient_id = p.patient_id AND ({match}))",
        {"t": f"%{term}%"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("include", [True, False], ids=["inclusion", "exclusion"])
@pytest.mark.parametrize("kind", sorted(KINDS))
async def test_a_medication_or_procedure_criterion_selects_by_that_record(kind, include):
    view, columns, term = KINDS[kind]
    criterion = RB.build_condition(term, term=term, concept_type=kind)
    requirements = RB.build_requirements(
        inclusion=[criterion] if include else [], exclusion=[] if include else [criterion]
    )
    sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        requirements, count_only=True
    )

    with_record = await _patients_with(view, columns, term)
    total = await _count("SELECT COUNT(*) FROM sqlonfhir.patient_demographics")
    assert 0 < with_record < total, "vacuous: the term must split the corpus"

    assert await _count(sql, params) == (with_record if include else total - with_record)
