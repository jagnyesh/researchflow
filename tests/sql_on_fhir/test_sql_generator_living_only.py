"""#403: a formal cohort with an age criterion counts living patients only.

Age is computed from today, which means nothing for a patient who has died,
so the gold set's age cases are living-only (repo owner, 2026-11-07, #241).
`deceased` is `deceased.exists()` in the patient_demographics ViewDefinition;
IS NOT TRUE keeps a patient whose flag is NULL. Requests without an age
criterion keep every patient: their signed-off oracles include the deceased.
"""

import pytest

from app.utils.sql_generator import SQLGenerator
from tests.fixtures import RequirementsBuilder as RB

LIVING = "p.deceased IS NOT TRUE"
OVER_65 = RB.build_demographic("Age > 65", term="age", details="> 65")
HYPERTENSION = RB.build_condition("hypertension")


def _where(requirements, count_only):
    sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        requirements, count_only=count_only
    )
    head, sep, where = sql.partition("\nWHERE ")
    assert sep, f"no WHERE clause; sql=\n{sql}"
    return where, params


@pytest.mark.parametrize("count_only", [True, False])
@pytest.mark.parametrize(
    "requirements",
    [
        RB.build_requirements(inclusion=[OVER_65, HYPERTENSION]),
        RB.build_requirements(inclusion=[HYPERTENSION], exclusion=[OVER_65]),
        RB.build_requirements(
            inclusion=[OVER_65],
            time_period={"start": "2025-01-01", "end": "2025-12-31"},
        ),
        RB.build_requirements(
            inclusion=[
                RB.build_demographic("65 or older", term="age", details="65 or older"),
                HYPERTENSION,
            ]
        ),
    ],
    ids=["inclusion", "exclusion", "time_period", "inclusive_age"],
)
def test_an_age_criterion_keeps_living_patients_only(requirements, count_only):
    where, params = _where(requirements, count_only)

    assert where.count(LIVING) == 1, where
    assert 65 in params.values()


@pytest.mark.parametrize("count_only", [True, False])
@pytest.mark.parametrize(
    "requirements",
    [
        RB.build_requirements(inclusion=[HYPERTENSION]),
        RB.build_requirements(inclusion=[RB.build_demographic("Female", term="female")]),
        RB.build_requirements(
            inclusion=[HYPERTENSION], exclusion=[RB.build_condition("diabetes mellitus")]
        ),
    ],
    ids=["condition", "gender", "condition_exclusion"],
)
def test_a_request_without_an_age_criterion_keeps_the_deceased(requirements, count_only):
    where, _ = _where(requirements, count_only)

    assert "deceased" not in where, where


# The filter follows the emitted age predicate, so an age it can't parse gets neither.
@pytest.mark.parametrize("details", ["elderly"])
def test_an_unparseable_age_adds_no_living_filter(details):
    vague = RB.build_demographic(details, term="age", details=details)
    where, params = _where(RB.build_requirements(inclusion=[vague, HYPERTENSION]), True)

    assert "deceased" not in where and "AGE(" not in where, where
    assert not any(name.startswith("age") for name in params), params


def test_the_living_filter_does_not_carry_over_to_the_next_query():
    generator = SQLGenerator(use_materialized_views=True)
    generator.generate_phenotype_sql(RB.build_requirements(inclusion=[OVER_65]), count_only=True)

    sql, _ = generator.generate_phenotype_sql(
        RB.build_requirements(inclusion=[HYPERTENSION]), count_only=True
    )

    assert "deceased" not in sql, sql
