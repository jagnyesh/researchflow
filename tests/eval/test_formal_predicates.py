"""#242: the emitted phenotype SQL carries every requested predicate, and
nothing the request didn't ask for.

A matching cohort isn't enough: on a small corpus a missing or extra
predicate can leave the patient set unchanged. Predicates are read from the
SQL's AST (sqlglot), with bound parameters resolved, and compared with the
case's required predicates. Pure: no database.
"""

import json
import re
from dataclasses import replace

import pytest

from app.utils.sql_generator import SQLGenerator
from tests.eval.formal_cases import FORMAL_CASES
from tests.eval.formal_harness import case_passes
from tests.eval.formal_predicates import check_predicates, extract_predicates
from tests.eval.formal_record import load_recording

# The checker tests below pin these predicate sets, so they keep testing the
# checker when a gold case's requirements change (#241 made case 1 living-only;
# #403 made the generator emit it).
CASE_1 = replace(
    FORMAL_CASES[0],
    required_predicates=[
        ("deceased", "=", False),
        ("gender", "=", "female"),
        ("age", ">", 65),
        ("condition", "has", "diabetes mellitus"),
    ],
)
CASE_2 = FORMAL_CASES[1]


def _sql(requirements):
    return SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        requirements, count_only=False
    )


def _recorded(case):
    return load_recording()[case.id]


def _without(requirements, term):
    keep = [
        c
        for c in requirements["inclusion_criteria"]
        if all(k.get("term") != term for k in c["concepts"])
    ]
    return {**requirements, "inclusion_criteria": keep}


@pytest.mark.parametrize(
    "case",
    [
        (
            pytest.param(c, marks=pytest.mark.xfail(strict=True, reason=c.expected_fail))
            if c.expected_fail
            else c
        )
        for c in FORMAL_CASES
    ],
    ids=lambda c: c.id,
)
def test_the_recorded_sql_carries_exactly_the_required_predicates(case):
    sql, params = _sql(_recorded(case))

    assert extract_predicates(sql, params) == set(case.required_predicates)
    assert check_predicates(case, sql, params) == (set(), set())


def test_a_dropped_criterion_is_reported_missing():
    sql, params = _sql(_without(_recorded(CASE_1), "gender"))

    missing, extra = check_predicates(CASE_1, sql, params)

    assert missing == {("gender", "=", "female")} and extra == set()


def test_an_unrequested_criterion_is_reported_extra():
    requirements = _recorded(CASE_1)
    hypertension = {
        "description": "hypertension",
        "concepts": [{"type": "condition", "term": "hypertension"}],
    }
    sql, params = _sql(
        {**requirements, "inclusion_criteria": [*requirements["inclusion_criteria"], hypertension]}
    )

    missing, extra = check_predicates(CASE_1, sql, params)

    assert missing == set() and extra == {("condition", "has", "hypertension")}


def test_a_broader_condition_match_is_both_missing_and_extra():
    sql, params = _sql(_recorded(CASE_1))
    params = {**params, **{k: "%diabetes%" for k, v in params.items() if "diabetes" in str(v)}}

    missing, extra = check_predicates(CASE_1, sql, params)

    assert ("condition", "has", "diabetes mellitus") in missing
    assert ("condition", "has", "diabetes") in extra


def test_an_unrecognized_predicate_is_extra_not_ignored():
    sql, params = _sql(_recorded(CASE_1))
    sql = sql.replace("WHERE ", "WHERE p.family_name IS NOT NULL AND ", 1)

    missing, extra = check_predicates(CASE_1, sql, params)

    assert missing == set()
    assert any(p[0] == "unrecognized" for p in extra), extra


def test_the_exclusion_is_matched_as_lacks():
    sql, params = _sql(_recorded(CASE_2))

    assert ("condition", "lacks", "diabetes mellitus") in extract_predicates(sql, params)


def test_the_living_filter_is_matched_as_not_deceased():
    sql, params = _sql(_recorded(CASE_1))

    assert ("deceased", "=", False) in extract_predicates(sql, params)


def test_required_predicates_are_json_safe_tuples():
    for case in FORMAL_CASES:
        assert all(isinstance(p, tuple) and len(p) == 3 for p in case.required_predicates)
        json.dumps([list(p) for p in case.required_predicates])


_CORRELATION = "WHERE c.patient_id = p.patient_id"
_LIKE = "LOWER(c.code_text) LIKE LOWER(:condition_3)"
_ALL_COLUMNS = (
    "(LOWER(c.code_text) LIKE LOWER(:condition_3) OR LOWER(c.icd10_display) LIKE "
    "LOWER(:condition_3) OR LOWER(c.snomed_display) LIKE LOWER(:condition_3))"
)
_AGE = "EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birth_date::date)) > :age_2"
_FROM = "FROM sqlonfhir.patient_demographics p\n"
_LIVING = "p.deceased IS NOT TRUE"

# Each rewrite keeps the required predicate set's labels but narrows or
# broadens the cohort; the shape match must flag every one (#242 review).
_SHAPE_ESCAPES = {
    "extra_inner_filter": (_CORRELATION, _CORRELATION + " AND c.clinical_status = 'active'"),
    "missing_correlation": (_CORRELATION + "\n        AND ", "WHERE "),
    "like_or_true": (_ALL_COLUMNS, "(" + _ALL_COLUMNS + " OR 1 = 1)"),
    "negated_like": (_ALL_COLUMNS, "NOT " + _ALL_COLUMNS),
    "one_column": (_ALL_COLUMNS, "(" + _LIKE + ")"),
    "birth_year_not_age": (_AGE, "EXTRACT(YEAR FROM p.birth_date) > :age_2"),
    "months_not_years": (_AGE, _AGE.replace("YEAR FROM AGE", "MONTH FROM AGE")),
    "compound_threshold": (_AGE, _AGE + " + 10"),
    "other_alias_gender": ("p.gender = :gender_1", "c.gender = :gender_1"),
    # = FALSE and IS FALSE drop a NULL flag; IS NULL drops deceased = false.
    "living_eq_false": (_LIVING, "p.deceased = FALSE"),
    "living_is_false": (_LIVING, "p.deceased IS FALSE"),
    "living_is_null": (_LIVING, "p.deceased IS NULL"),
    "living_other_alias": (_LIVING, "c.deceased IS NOT TRUE"),
    "join_filter": (
        _FROM,
        _FROM.rstrip("\n")
        + " JOIN sqlonfhir.condition_simple c ON c.patient_id = p.patient_id"
        + " AND c.clinical_status = 'active'\n",
    ),
    "from_subquery": (
        _FROM,
        "FROM (SELECT * FROM sqlonfhir.patient_demographics WHERE deceased IS NULL) p\n",
    ),
}


@pytest.mark.parametrize("old,new", _SHAPE_ESCAPES.values(), ids=list(_SHAPE_ESCAPES))
def test_a_reshaped_predicate_is_not_matched(old, new):
    sql, params = _sql(_recorded(CASE_1))
    assert old in sql
    sql = sql.replace(old, new, 1)

    missing, extra = check_predicates(CASE_1, sql, params)

    assert missing or extra, sql


def test_a_one_column_medication_match_is_not_the_oracle_match():
    insulin = next(c for c in FORMAL_CASES if c.id == "diabetes_mellitus_not_on_insulin")
    sql, params = _sql(_recorded(insulin))
    one_column = re.sub(r" OR LOWER\(x\.medication_text\) LIKE LOWER\(:\w+\)", "", sql)
    assert one_column != sql

    missing, extra = check_predicates(insulin, one_column, params)

    assert ("medication", "lacks", "insulin") in missing and extra


def test_a_prefix_pattern_is_not_the_requested_contains_match():
    sql, params = _sql(_recorded(CASE_1))
    params = {k: "diabetes mellitus%" if "diabetes" in str(v) else v for k, v in params.items()}

    missing, extra = check_predicates(CASE_1, sql, params)

    assert ("condition", "has", "diabetes mellitus") in missing and extra


def test_a_missing_predicate_alone_fails_the_case():
    assert case_passes(0, False, set(), set())
    assert not case_passes(0, False, {("gender", "=", "female")}, set())
    assert not case_passes(0, False, set(), {("gender", "=", "female")})
