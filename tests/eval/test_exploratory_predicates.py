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
    # The view stores 'female'; Postgres = is case-sensitive, so this selects nobody.
    "gender_upper_case": (_GENDER, "p.gender = 'FEMALE'", {("gender", "=", "female")}),
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


_MED = _CASES["female_with_medication"]
_COUNT_MEDS = "SELECT COUNT(DISTINCT m.patient_id) FROM sqlonfhir.medication_requests m "

# A source that isn't linked on patient_id leaves the counted rows unrestricted
# by a predicate on it, so the predicate doesn't survive (review finding 2).
_UNLINKED = {
    "comma_join": ", sqlonfhir.patient_demographics p",
    "cross_join": "CROSS JOIN sqlonfhir.patient_demographics p",
    "on_true": "JOIN sqlonfhir.patient_demographics p ON TRUE",
    "other_column": "JOIN sqlonfhir.patient_demographics p ON p.gender = m.status",
    "patient_id_to_itself": "JOIN sqlonfhir.patient_demographics p ON p.patient_id = p.patient_id",
    "using": "JOIN sqlonfhir.patient_demographics p USING (patient_id)",
    "link_under_or": "JOIN sqlonfhir.patient_demographics p ON m.patient_id = p.patient_id OR TRUE",
    "link_to_a_later_source": (
        "JOIN sqlonfhir.patient_demographics p ON p.patient_id = c.patient_id "
        "JOIN sqlonfhir.condition_simple c ON c.patient_id = m.patient_id"
    ),
    "link_between_earlier_sources": (
        "JOIN sqlonfhir.patient_demographics p ON m.patient_id = m.patient_id"
    ),
}


@pytest.mark.parametrize("join", _UNLINKED.values(), ids=list(_UNLINKED))
def test_a_predicate_on_an_unlinked_patient_table_counts_as_missing(join):
    sql = _COUNT_MEDS + join + " WHERE p.gender = 'female'"

    assert missing_predicates(_MED, sql) == {("gender", "=", "female")}


def test_a_predicate_on_a_patient_id_linked_table_survives():
    sql = (
        _COUNT_MEDS + "JOIN sqlonfhir.patient_demographics p "
        "ON m.patient_id = p.patient_id AND p.active WHERE p.gender = 'female'"
    )

    assert missing_predicates(_MED, sql) == set()


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


_UNREADABLE = {
    "unparseable": "SELEC COUNT(* FROM",
    "non_decimal_digit": (
        "SELECT COUNT(*) FROM sqlonfhir.patient_demographics p "
        "WHERE p.birth_date::date > CURRENT_DATE - INTERVAL '²' YEAR"
    ),
}


@pytest.mark.parametrize("sql", _UNREADABLE.values(), ids=list(_UNREADABLE))
def test_sql_that_cant_be_read_misses_every_stated_predicate(sql):
    # Review finding 5: one bad SQL string mustn't crash the summary of a billed run.
    case = _CASES["female_under_65"]

    assert missing_predicates(case, sql) == set(case.required_predicates)
    rows = [
        {
            "id": case.id,
            "kind": "scored",
            "matched": False,
            "escaped": None,
            "cost_usd": None,
            "sql": sql,
        }
    ]
    assert summarize(rows, n_unsupported=0)["predicate_survived"] == 0


_UNDER_65 = "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p WHERE "

# Review finding 6: each guard against a false survival of age < 65 or gender.
_NOT_THE_PREDICATE = {
    "extract_month": "EXTRACT(MONTH FROM AGE(CURRENT_DATE, p.birth_date::date)) < 65",
    "age_from_another_date": "EXTRACT(YEAR FROM AGE(DATE '2000-01-01', p.birth_date::date)) < 65",
    "cast_to_text": "p.birth_date::text > CURRENT_DATE - INTERVAL '65 years'",
    "interval_from_another_date": "p.birth_date::date > DATE '2000-01-01' - INTERVAL '65 years'",
    "string_bound": "EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birth_date::date)) < '65'",
}


@pytest.mark.parametrize("where", _NOT_THE_PREDICATE.values(), ids=list(_NOT_THE_PREDICATE))
def test_a_near_miss_age_form_counts_as_missing(where):
    assert ("age", "<", 65) in missing_predicates(_CASES["age_under_65"], _UNDER_65 + where)


def test_a_table_outside_the_sqlonfhir_schema_is_not_the_patient_table():
    sql = _RECORDED["gender_female"][0].replace("sqlonfhir.", "public.")

    assert missing_predicates(_CASES["gender_female"], sql) == {("gender", "=", "female")}


@pytest.mark.parametrize(
    "where",
    [
        "CURRENT_DATE - INTERVAL '65 years' < p.birth_date::date",
        "65 > EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birth_date::date))",
    ],
    ids=["birth_date", "extract"],
)
def test_a_mirrored_age_comparison_flips_its_operator(where):
    assert missing_predicates(_CASES["age_under_65"], _UNDER_65 + where) == set()
