"""#404: an age criterion keeps its boundary: inclusive phrasings give >= or <=.

Before #404 the parser knew only > and <, so "65 or older" emitted no age
predicate and ">= 65" became > 65, dropping patients who are exactly 65.
"""

import re

import pytest

from app.utils.sql_generator import SQLGenerator
from tests.fixtures import RequirementsBuilder as RB

_AGE_COMPARISON = re.compile(r"AGE\(CURRENT_DATE, p\.birth_date::date\)\) (>=|<=|>|<) :(\w+)")


def _age_predicate(details):
    age = RB.build_demographic(details, term="age", details=details)
    sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        RB.build_requirements(inclusion=[age, RB.build_condition("hypertension")]),
        count_only=True,
    )
    found = _AGE_COMPARISON.findall(sql)
    assert len(found) == 1, f"expected one age comparison; sql=\n{sql}"
    op, name = found[0]
    return op, params[name], sql


@pytest.mark.parametrize(
    "details",
    ["65 or older", "at least 65", ">= 65", "65 or over", "greater than or equal to 65"],
)
def test_an_inclusive_lower_bound_keeps_the_boundary_age(details):
    op, value, _ = _age_predicate(details)

    assert (op, value) == (">=", 65)


@pytest.mark.parametrize(
    "details",
    ["50 or younger", "at most 50", "<= 50", "50 or under", "less than or equal to 50"],
)
def test_an_inclusive_upper_bound_keeps_the_boundary_age(details):
    op, value, _ = _age_predicate(details)

    assert (op, value) == ("<=", 50)


@pytest.mark.parametrize(
    "details", ["over 65", "older than 65", "> 65", "senior over 65", "for older than 65"]
)
def test_an_exclusive_lower_bound_stays_strict(details):
    op, value, _ = _age_predicate(details)

    assert (op, value) == (">", 65)


@pytest.mark.parametrize("details", ["under 50", "younger than 50", "< 50", "minor under 50"])
def test_an_exclusive_upper_bound_stays_strict(details):
    op, value, _ = _age_predicate(details)

    assert (op, value) == ("<", 50)


# ADR 0035: the living-only filter follows the age predicate the generator emits.
@pytest.mark.parametrize("details", ["65 or older", "at least 65", "50 or younger", "at most 50"])
def test_a_newly_parsed_age_brings_the_living_filter(details):
    _, _, sql = _age_predicate(details)

    assert sql.count("p.deceased IS NOT TRUE") == 1, sql
