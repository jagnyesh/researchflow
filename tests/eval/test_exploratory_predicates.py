"""#142: the recorded exploratory SQL carries every gender and age predicate
its request states (ADR 0042).

The replay gate compares counts with an oracle, which a dropped predicate can
pass on CI's small seed (0 == 0). This reads the predicates from the SQL's AST
instead. Pure: no database, no API key.
"""

import pytest

from tests.eval.cases import scored_cases
from tests.eval.exploratory_predicates import missing_predicates
from tests.eval.harness import fixture_path, load_fixture, summarize

_RECORDED = load_fixture(fixture_path("claude-sonnet-4-6"))
_STATED = [c for c in scored_cases() if c.required_predicates]


@pytest.mark.parametrize("case", _STATED, ids=lambda c: c.id)
def test_the_recorded_sql_carries_every_stated_predicate(case):
    sql, _ = _RECORDED[case.id]

    assert missing_predicates(case, sql) == set()


def test_the_demographic_cases_state_their_predicates():
    assert {c.id for c in _STATED} >= {
        "gender_female",
        "gender_male",
        "age_under_65",
        "age_over_18",
        "female_under_65",
        "female_hypertension_under_65",
        "male_over_18_diabetes",
        "female_with_medication",
    }


_CASES = {c.id: c for c in scored_cases()}
_JOINED = _CASES["female_hypertension_under_65"]
_GENDER = "p.gender = 'female'"
_AGE = "p.birth_date::date > CURRENT_DATE - INTERVAL '65 years'"

# Each rewrite drops, moves or changes a stated predicate; it must count as missing.
_RESHAPED = {
    "age_dropped": (_AGE + " AND ", "", {("age", "<", 65)}),
    "age_under_or": (_AGE, "(" + _AGE + " OR 1 = 1)", {("age", "<", 65)}),
    "age_off_by_a_day": (_AGE, _AGE.replace(" > ", " >= "), {("age", "<", 65)}),
    "age_other_threshold": (_AGE, _AGE.replace("65", "64"), {("age", "<", 65)}),
    "age_in_months": (_AGE, _AGE.replace("years", "months"), {("age", "<", 65)}),
    "age_on_other_table": (_AGE, _AGE.replace("p.", "c."), {("age", "<", 65)}),
    "gender_on_other_table": (_GENDER, "c.gender = 'female'", {("gender", "=", "female")}),
    "gender_negated": (_GENDER, "NOT " + _GENDER, {("gender", "=", "female")}),
    "gender_other_value": (_GENDER, "p.gender = 'male'", {("gender", "=", "female")}),
    "gender_unqualified_in_a_join": (_GENDER, "gender = 'female'", {("gender", "=", "female")}),
}


@pytest.mark.parametrize("old,new,missing", _RESHAPED.values(), ids=list(_RESHAPED))
def test_a_reshaped_predicate_counts_as_missing(old, new, missing):
    sql, _ = _RECORDED[_JOINED.id]
    assert old in sql
    sql = sql.replace(old, new, 1)

    assert missing_predicates(_JOINED, sql) == missing


def test_a_predicate_inside_a_from_subquery_counts_as_missing():
    sql = (
        "SELECT COUNT(DISTINCT p.patient_id) FROM (SELECT * FROM sqlonfhir.patient_demographics "
        "WHERE gender = 'female' AND birth_date::date > CURRENT_DATE - INTERVAL '65 years') p"
    )

    assert missing_predicates(_CASES["female_under_65"], sql) == {
        ("gender", "=", "female"),
        ("age", "<", 65),
    }


def test_no_sql_misses_every_stated_predicate():
    assert missing_predicates(_JOINED, None) == set(_JOINED.required_predicates)


def test_the_summary_reports_predicate_survival_over_the_stated_cases():
    def row(case_id, sql):
        return {
            "id": case_id,
            "kind": "scored",
            "matched": True,
            "escaped": None,
            "cost_usd": None,
            "sql": sql,
        }

    rows = [
        row("female_under_65", _RECORDED["female_under_65"][0]),
        row("gender_male", None),  # refused: nothing survives
        row("total_patients", "SELECT COUNT(*) FROM sqlonfhir.patient_demographics"),
    ]

    s = summarize(rows, n_unsupported=0)

    assert (s["predicate_survived"], s["predicate_stated"]) == (1, 2)
    assert s["predicate_survival"] == 0.5


def test_equivalent_forms_survive():
    sql = (
        "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p "
        "WHERE 'female' = p.gender "
        "AND EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birth_date::date)) < 65"
    )

    assert missing_predicates(_CASES["female_under_65"], sql) == set()
