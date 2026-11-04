"""#242: the emitted phenotype SQL carries every requested predicate, and
nothing the request didn't ask for.

A matching cohort isn't enough: on a small corpus a missing or extra
predicate can leave the patient set unchanged. Predicates are read from the
SQL's AST (sqlglot), with bound parameters resolved, and compared with the
case's required predicates. Pure: no database.
"""

import json

import pytest

from app.utils.sql_generator import SQLGenerator
from tests.eval.formal_cases import FORMAL_CASES
from tests.eval.formal_predicates import check_predicates, extract_predicates
from tests.eval.formal_record import load_recording

CASE_1, CASE_2 = FORMAL_CASES


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


@pytest.mark.parametrize("case", FORMAL_CASES, ids=lambda c: c.id)
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


def test_required_predicates_are_json_safe_tuples():
    for case in FORMAL_CASES:
        assert all(isinstance(p, tuple) and len(p) == 3 for p in case.required_predicates)
        json.dumps([list(p) for p in case.required_predicates])
