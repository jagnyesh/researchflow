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


# #431 (ADR 0043): "65 and over" built > 65, dropping every patient who is exactly 65.
@pytest.mark.parametrize(
    "details", ["65 and over", "65 and above", "65 and older", "65 and up", "65 years and over"]
)
def test_a_trailing_and_lower_bound_keeps_the_boundary_age(details):
    op, value, _ = _age_predicate(details)

    assert (op, value) == (">=", 65)


# "18 and under" built < 18.
@pytest.mark.parametrize("details", ["18 and under", "18 and below", "18 and younger"])
def test_a_trailing_and_upper_bound_keeps_the_boundary_age(details):
    op, value, _ = _age_predicate(details)

    assert (op, value) == ("<=", 18)


# These built no age predicate, so the request failed.
@pytest.mark.parametrize(
    "details,expected",
    [
        ("65 or more", (">=", 65)),
        ("65 or greater", (">=", 65)),
        ("65 or higher", (">=", 65)),
        ("50 or less", ("<=", 50)),
        ("50 or fewer", ("<=", 50)),
        ("50 or lower", ("<=", 50)),
    ],
)
def test_an_or_more_or_less_bound_keeps_the_boundary_age(details, expected):
    op, value, _ = _age_predicate(details)

    assert (op, value) == expected


# "=> 65" and "=< 50" built strict bounds; the others built no age predicate.
@pytest.mark.parametrize(
    "details,expected",
    [
        ("≥ 65", (">=", 65)),
        ("=> 65", (">=", 65)),
        ("65+", (">=", 65)),
        ("65 +", (">=", 65)),
        ("65+ years", (">=", 65)),
        ("≤ 50", ("<=", 50)),
        ("=< 50", ("<=", 50)),
    ],
)
def test_an_inclusive_symbol_keeps_the_boundary_age(details, expected):
    op, value, _ = _age_predicate(details)

    assert (op, value) == expected


def _generate_with_age(side, details):
    age = RB.build_demographic(details, term="age", details=details)
    return SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        RB.build_requirements(**{side: [age]}), count_only=True
    )


# One number and both directions has no safe reading; the parser used to take
# whichever comparison it checked first.
@pytest.mark.parametrize("side", ["inclusion", "exclusion"])
@pytest.mark.parametrize(
    "details", ["under 65 and over", "65 and over or under", "over 65 or younger", "≥ 65 or < "]
)
def test_an_age_naming_both_directions_for_one_number_fails_the_request(side, details):
    with pytest.raises(ValueError, match="A demographic concept produced no SQL condition"):
        _generate_with_age(side, details)


_AGE = "EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birth_date::date))"


# ADR 0039 reads each side of a two-bound age with the single-bound parser, so
# "under 18 or 65 and over" built > 65 and dropped the 65-year-olds.
@pytest.mark.parametrize(
    "details,join,first,second",
    [
        ("under 18 or 65 and over", "OR", ("<", 18), (">=", 65)),
        ("18 and under or 65 and over", "OR", ("<=", 18), (">=", 65)),
        ("17 or less or 65+", "OR", ("<=", 17), (">=", 65)),
        ("18+ and under 65", "AND", (">=", 18), ("<", 65)),
        ("18 and over and under 65", "AND", (">=", 18), ("<", 65)),
        ("18 or more and under 65", "AND", (">=", 18), ("<", 65)),
        ("≥ 18 and =< 65", "AND", (">=", 18), ("<=", 65)),
    ],
)
def test_a_two_bound_age_reads_inclusive_phrasings_on_both_sides(details, join, first, second):
    sql, params = _generate_with_age("inclusion", details)

    assert f"({_AGE} {first[0]} :age_1 {join} {_AGE} {second[0]} :age_2)" in sql
    assert params == {"age_1": first[1], "age_2": second[1]}
    assert sql.count("p.deceased IS NOT TRUE") == 1, sql


# Reads as "<= 18" and a stray 65, or as ">= 18 and < 65"; it failed before #431 too.
@pytest.mark.parametrize("side", ["inclusion", "exclusion"])
def test_a_bare_and_under_between_two_numbers_fails_the_request(side):
    with pytest.raises(ValueError, match="A demographic concept produced no SQL condition"):
        _generate_with_age(side, "18 and under 65")


# ADR 0043 keeps ADR 0039's rule: #431's negated rows fail instead of building <= or >=.
@pytest.mark.parametrize("side", ["inclusion", "exclusion"])
@pytest.mark.parametrize(
    "details",
    [
        "no older than 65",
        "not over 65",
        "no less than 65",
        "not younger than 65",
        "no more than 50",
    ],
)
def test_a_negated_comparative_age_still_fails_the_request(side, details):
    with pytest.raises(ValueError, match="A demographic concept produced no SQL condition"):
        _generate_with_age(side, details)


@pytest.mark.parametrize(
    "details", ["65 and over", "18 and under", "65 or more", "50 or less", "65+", "≥ 65", "≤ 50"]
)
def test_an_age_parsed_since_431_brings_the_living_filter(details):
    _, _, sql = _age_predicate(details)

    assert sql.count("p.deceased IS NOT TRUE") == 1, sql


# Review of #431: a quantity word elsewhere in the details turned a strict bound
# inclusive ("> 18 (one or more encounters)" built >= 18). The quantity forms now
# count only right after the age.
@pytest.mark.parametrize(
    "details,expected",
    [
        ("> 18 (one or more encounters)", (">", 18)),
        ("under 18 with one or fewer visits", ("<", 18)),
        ("> 65 and up to date on vaccines", (">", 65)),
        ("< 18 (pediatric, one or more visits)", ("<", 18)),
        ("65 years or more", (">=", 65)),
        ("65 years of age or more", (">=", 65)),
        ("50 years old or less", ("<=", 50)),
    ],
)
def test_a_quantity_word_counts_only_right_after_the_age(details, expected):
    op, value, _ = _age_predicate(details)

    assert (op, value) == expected


# A strict and an inclusive form for one bound have no single reading: "> 65 or more"
# built >= 65 and "under 65 or younger" built <= 65. "+" needs the age before it.
@pytest.mark.parametrize("side", ["inclusion", "exclusion"])
@pytest.mark.parametrize(
    "details",
    [
        "> 65 or more",
        "over 65 and up",
        "under 65 or younger",
        "over 18 or higher risk",
        "18 or older and under 65 or less",
        "18 or older and under 65 or younger",
        "+65",
    ],
)
def test_an_age_mixing_strict_and_inclusive_forms_fails_the_request(side, details):
    with pytest.raises(ValueError, match="A demographic concept produced no SQL condition"):
        _generate_with_age(side, details)
