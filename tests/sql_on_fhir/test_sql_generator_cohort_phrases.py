"""#456 (ADR 0039): details that change a concept's meaning build that meaning, or fail.

Each phrase here used to build a predicate with another meaning, so the cohort
changed without an error.
"""

import pytest

from app.utils.sql_generator import SQLGenerator
from tests.fixtures import RequirementsBuilder as RB


def _generate(inclusion=(), exclusion=()):
    return SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        RB.build_requirements(inclusion=list(inclusion), exclusion=list(exclusion)),
        count_only=True,
    )


def _criterion(*concepts):
    return {"description": "criterion", "concepts": list(concepts), "codes": []}


# No view reads FamilyMemberHistory, so the patient's own condition is the only
# thing the generator could match, which is wrong in either list.
@pytest.mark.parametrize("side", ["inclusion", "exclusion"])
@pytest.mark.parametrize("details", ["family history", "Family  History of, maternal"])
def test_a_family_history_condition_fails_the_request(side, details):
    concept = {"type": "condition", "term": "breast cancer", "details": details}

    with pytest.raises(ValueError, match="family history") as raised:
        _generate(**{side: [_criterion(concept)]})

    assert "breast cancer" not in str(raised.value)


@pytest.mark.parametrize(
    "term,details,value",
    [
        ("male", "", "male"),
        ("gender", "female", "female"),
        ("female", "female patients", "female"),
        # Inside an exclusion the marker restates the list (ADR 0036), so it is no negation.
        ("gender", "male, excluded", "male"),
    ],
)
def test_a_single_gender_builds_that_gender(term, details, value):
    concept = {"type": "demographic", "term": term, "details": details}

    sql, params = _generate(exclusion=[_criterion(concept)])

    assert "(p.gender = :gender_1) IS NOT TRUE" in sql
    assert params == {"gender_1": value}


# Each used to build one gender: "not male" built male, "male or female" built female.
@pytest.mark.parametrize("side", ["inclusion", "exclusion"])
@pytest.mark.parametrize(
    "term,details",
    [
        ("gender", "not male"),
        ("gender", "male or female"),
        ("female", "or male"),
        ("gender", "non-binary"),
        ("gender", "non-male"),
        ("gender", "anyone except female"),
        ("gender", "other than male"),
        ("gender", "excluding males"),
        ("male", "no"),
        ("gender", "without female"),
    ],
)
def test_a_negated_or_multi_value_gender_fails_the_request(side, term, details):
    concept = {"type": "demographic", "term": term, "details": details}

    with pytest.raises(ValueError, match="A demographic concept produced no SQL condition"):
        _generate(**{side: [_criterion(concept)]})


_AGE = "EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birth_date::date))"


def _age(details):
    return _criterion({"type": "demographic", "term": "age", "details": details})


# The parser used to take the first number, so "> 18 and < 65" kept only > 18.
@pytest.mark.parametrize(
    "details,lo_op,lo,hi_op,hi",
    [
        ("> 18 and < 65", ">", 18, "<", 65),
        (">= 18 and <= 65", ">=", 18, "<=", 65),
        ("18 or older and under 65", ">=", 18, "<", 65),
        ("under 65 and over 18", ">", 18, "<", 65),
    ],
)
def test_an_age_with_two_bounds_joined_by_and_builds_both(details, lo_op, lo, hi_op, hi):
    sql, params = _generate(inclusion=[_age(details)])

    assert f"({_AGE} {lo_op} :age_1 AND {_AGE} {hi_op} :age_2)" in sql
    assert params == {"age_1": lo, "age_2": hi}
    assert "p.deceased IS NOT TRUE" in sql


# "under 18 or over 65" used to read "or over" as the inclusive "18 or over".
@pytest.mark.parametrize(
    "details,lo_op,lo,hi_op,hi",
    [
        ("under 18 or over 65", "<", 18, ">", 65),
        ("< 18 or > 65", "<", 18, ">", 65),
        ("over 65 or under 18", "<", 18, ">", 65),
        ("18 or younger or 65 or older", "<=", 18, ">=", 65),
    ],
)
def test_an_age_with_two_bounds_joined_by_or_builds_outside_the_range(
    details, lo_op, lo, hi_op, hi
):
    sql, params = _generate(inclusion=[_age(details)])

    assert f"({_AGE} {lo_op} :age_1 OR {_AGE} {hi_op} :age_2)" in sql
    assert params == {"age_1": lo, "age_2": hi}


def test_an_excluded_two_bound_age_keeps_unknown_birth_dates():
    sql, _ = _generate(exclusion=[_age("under 18 or over 65")])

    assert f"(({_AGE} < :age_1 OR {_AGE} > :age_2)) IS NOT TRUE" in sql
    assert "p.deceased IS NOT TRUE" in sql


@pytest.mark.parametrize("side", ["inclusion", "exclusion"])
@pytest.mark.parametrize(
    "details",
    [
        "> 65 and < 18",  # no one
        "> 18 or < 65",  # everyone with a birth date
        "> 18 and > 65",  # two lower bounds
        "under 18 or over 18",  # no gap between the bounds
        "18 to 65",  # no connective
        "> 18 and or < 65",  # two connectives
        "> 65 within last 6 months",
        "> 18, < 65 and < 70",  # three numbers
    ],
)
def test_any_other_age_with_two_or_more_numbers_fails_the_request(side, details):
    with pytest.raises(ValueError, match="A demographic concept produced no SQL condition"):
        _generate(**{side: [_age(details)]})


async def _count(sql, params=None):
    from app.adapters.sql_on_fhir import SQLonFHIRAdapter

    rows = await SQLonFHIRAdapter().execute_sql(sql, params)
    return rows[0][next(iter(rows[0]))]


# Birth-date arithmetic, not AGE(): age > 18 is a birth date at least 19 years ago.
_LIVING = "SELECT COUNT(*) FROM sqlonfhir.patient_demographics WHERE deceased IS NOT TRUE AND "
_BORN = "birth_date::date {} CURRENT_DATE - INTERVAL '{} years'"


@pytest.mark.requires_services
@pytest.mark.asyncio
async def test_two_bound_ages_count_what_a_hand_written_query_counts():
    adults = await _count(*_generate(inclusion=[_age("> 18 and < 65")]))
    outside = await _count(*_generate(inclusion=[_age("under 18 or over 65")]))

    hand_adults = await _count(
        _LIVING + _BORN.format("<=", 19) + " AND " + _BORN.format(">", 65)  # nosec B608 - constants
    )
    hand_outside = await _count(
        _LIVING + f"({_BORN.format('>', 18)} OR {_BORN.format('<=', 66)})"  # nosec B608 - constants
    )
    aged_18_or_65 = await _count(
        _LIVING  # nosec B608 - constants
        + f"(({_BORN.format('<=', 18)} AND {_BORN.format('>', 19)})"
        + f" OR ({_BORN.format('<=', 65)} AND {_BORN.format('>', 66)}))"
    )
    living = await _count(_LIVING + "birth_date IS NOT NULL")  # nosec B608 - constants

    assert (adults, outside) == (hand_adults, hand_outside)
    assert 0 < adults < living and 0 < outside < living
    assert adults + outside + aged_18_or_65 == living
