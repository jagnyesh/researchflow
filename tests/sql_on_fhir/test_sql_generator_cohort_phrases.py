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
@pytest.mark.parametrize(
    "term,details",
    [
        ("breast cancer", "family history"),
        ("breast cancer", "Family  History of, maternal"),
        ("breast cancer", "family-history"),
        ("breast cancer", "family medical history"),
        ("breast cancer", "family hx"),
        ("family history of breast cancer", ""),
        ("breast cancer", "family_history"),
        ("breast cancer", "maternal history"),
        ("breast cancer", "Paternal  history"),
        ("breast cancer", "in a first-degree relative"),
    ],
)
def test_a_family_history_condition_fails_the_request(side, term, details):
    concept = {"type": "condition", "term": term, "details": details}

    with pytest.raises(ValueError, match="family history") as raised:
        _generate(**{side: [_criterion(concept)]})

    assert "breast cancer" not in str(raised.value)


# "familial" and "FH" also name a patient's own diagnosis, so they are not markers.
def test_familial_hypercholesterolemia_is_the_patients_own_condition():
    concept = {"type": "condition", "term": "familial hypercholesterolemia", "details": "FH"}

    _, params = _generate(inclusion=[_criterion(concept)])

    assert params == {"condition_1": "%familial hypercholesterolemia%"}


# ADR 0039 scopes the family-history rule to conditions.
@pytest.mark.parametrize("concept_type", ["medication", "procedure", "lab"])
def test_family_history_details_on_another_concept_type_still_build(concept_type):
    concept = {"type": concept_type, "term": "insulin", "details": "family history"}

    sql, _ = _generate(inclusion=[_criterion(concept)])

    assert sql.count("EXISTS (") == 1


@pytest.mark.parametrize(
    "term,details,value",
    [
        ("male", "", "male"),
        ("gender", "female", "female"),
        ("female", "female patients", "female"),
        ("gender", "males", "male"),
        ("Females", "", "female"),
        # "exclu" is a negation stem, but "exclusively" negates nothing.
        ("gender", "exclusively male", "male"),
        ("male", "male exclusively", "male"),
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
        ("gender", "exclude males"),
        ("gender", "excludes male patients"),
        ("gender", "anything but male"),
        ("gender", "isn't male"),
        ("gender", "isn’t male"),
        ("gender", "exclusion of males"),
        ("gender", "males (exclusion)"),
        ("gender", "excl. males"),
        ("gender", "excepting males"),
        ("gender", "omit males"),
        ("gender", "never male"),
        ("gender", "w/o males"),
        ("gender", "minus males"),
        ("gender", "besides males"),
        ("gender", "aside from males"),
        ("gender", "rather than male"),
        ("gender", "instead of male"),
        ("gender", "males are ineligible"),
        ("gender", "males removed"),
        ("gender", "males disqualified"),
        ("gender", "cannot be male"),
        ("gender", "nonmale"),
        ("gender", "exclusive of males"),
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
        (">= 18 and <= 18", ">=", 18, "<=", 18),
        ("18 or over and under 65", ">=", 18, "<", 65),
        ("18 or above and below 65", ">=", 18, "<", 65),
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
        ("under 18 or over 18", "<", 18, ">", 18),
        ("17 or under or over 65", "<=", 17, ">", 65),
        ("17 or below or over 65", "<=", 17, ">", 65),
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
        "> 18 and < 19",  # no whole year fits
        "<= 17 or >= 18",  # leaves out no whole year
        "18 to 65",  # no connective
        "> 18 and or < 65",  # two connectives
        "> 65 within last 6 months",
        "> 18, < 65 and < 70",  # three numbers
    ],
)
def test_any_other_age_with_two_or_more_numbers_fails_the_request(side, details):
    with pytest.raises(ValueError, match="A demographic concept produced no SQL condition"):
        _generate(**{side: [_age(details)]})


def test_exclusively_is_not_a_negation_for_an_age():
    sql, params = _generate(inclusion=[_age("exclusively over 65")])

    assert f"{_AGE} > :age_1" in sql
    assert params == {"age_1": 65}


# A negation used to build the inverse: "not over 65" built > 65.
@pytest.mark.parametrize("side", ["inclusion", "exclusion"])
@pytest.mark.parametrize(
    "details",
    [
        "excluding those under 18 or over 65",
        "not under 18 or over 65",
        "except under 18 or over 65",
        "exclude patients > 18 and < 65",
        "not over 65",
        "no one under 18",
        "not between 18 and 65",
        "over 18 but under 65",  # "but" is on the shared negation list
        "isn’t over 65",
        "don’t include over 65",
        "cannot be over 65",
        "nobody over 65",
        "none over 65",
        "never over 65",
        "w/o patients over 65",
        "over 65 disqualified",
        "under 18 or over 65 are ineligible",
        "exclusion: under 18 or over 65",
        "excl. under 18 or over 65",
        "excepting under 18 or over 65",
        "omit under 18 or over 65",
        "over 65 removed",
        "exclusive of over 65",
        "between 18 and 65 exclusive",  # meant strict bounds, not BETWEEN
    ],
)
def test_a_negated_age_fails_the_request(side, details):
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
