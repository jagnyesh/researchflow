"""#310 (ADR 0036): every criterion concept becomes SQL, or the request fails.

A concept the generator can't build used to be dropped with a log line, so the
cohort silently grew. The error names the concept's type and never its term or
details, which are PHI-adjacent.
"""

import pytest

from app.utils.sql_generator import SQLGenerator
from tests.fixtures import RequirementsBuilder as RB

DIABETES = {"type": "condition", "term": "diabetes"}
# A term and details that must never appear in the error.
SECRET = "zz-term-sentinel"


def _generate(inclusion=(), exclusion=()):
    return SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        RB.build_requirements(inclusion=list(inclusion), exclusion=list(exclusion)),
        count_only=True,
    )


def _criterion(*concepts):
    return {"description": SECRET, "concepts": list(concepts), "codes": []}


UNBUILDABLE = {
    "race": ({"type": "demographic", "term": "race", "details": SECRET}, "demographic"),
    "unparseable_age": ({"type": "demographic", "term": "age", "details": SECRET}, "demographic"),
    "unknown_type": ({"type": "allergy", "term": SECRET}, "unsupported concept type"),
}


@pytest.mark.parametrize("side", ["inclusion", "exclusion"])
@pytest.mark.parametrize("case", sorted(UNBUILDABLE))
def test_a_concept_that_builds_nothing_fails_the_request(case, side):
    concept, named = UNBUILDABLE[case]
    # Next to a concept that does build, in the same criterion.
    criterion = _criterion(DIABETES, concept)

    with pytest.raises(ValueError) as raised:
        _generate(**{side: [criterion]})

    assert named in str(raised.value)
    assert SECRET not in str(raised.value)


# The extraction prompt writes negation into details ("not on warfarin" ->
# details "excluded"); ignoring it inside an inclusion emits the inverse cohort.
MARKED_EXCLUDED = {
    "condition": {"type": "condition", "term": "cancer", "details": "excluded, any malignancy"},
    "medication": {"type": "medication", "term": "warfarin", "details": "excluded"},
    "procedure": {"type": "procedure", "term": "colonoscopy", "details": "Excluded — no history"},
    "lab": {"type": "lab", "term": "lactate", "details": "excluded"},
    "demographic": {"type": "demographic", "term": "age", "details": "< 18 excluded"},
}


@pytest.mark.parametrize("kind", sorted(MARKED_EXCLUDED))
def test_an_inclusion_concept_marked_excluded_fails_the_request(kind):
    with pytest.raises(ValueError) as raised:
        _generate(inclusion=[_criterion(DIABETES, MARKED_EXCLUDED[kind])])

    assert kind in str(raised.value) and "exclusion" in str(raised.value)
    assert MARKED_EXCLUDED[kind]["term"] not in str(raised.value)


@pytest.mark.parametrize("kind", sorted(MARKED_EXCLUDED))
def test_an_exclusion_concept_marked_excluded_is_negated_once(kind):
    sql, _ = _generate(
        inclusion=[_criterion(DIABETES)], exclusion=[_criterion(MARKED_EXCLUDED[kind])]
    )

    # The living filter an age adds is IS NOT TRUE too; it isn't the negation.
    where = sql.partition("WHERE ")[2].replace("p.deceased IS NOT TRUE", "")
    assert "NOT EXISTS" in where or "IS NOT TRUE" in where, where
    assert "NOT NOT" not in where and "IS NOT TRUE) IS NOT TRUE" not in where, where


def test_a_word_containing_excluded_is_not_a_marker():
    sql, _ = _generate(
        inclusion=[_criterion({"type": "condition", "term": "asthma", "details": "nonexcluded"})]
    )

    assert "EXISTS" in sql


# A blank term would build LIKE '%%' (every record) or '%None%' (almost none),
# and a non-string one '%['a', 'b']%' (nothing).
@pytest.mark.parametrize("term", ["", "   ", None, ["insulin", "metformin"], {"t": 1}, 0])
@pytest.mark.parametrize("kind", ["condition", "lab", "medication", "procedure"])
def test_a_concept_without_a_text_term_fails_the_request(kind, term):
    with pytest.raises(ValueError, match=f"^A {kind} concept produced no SQL condition$"):
        _generate(inclusion=[_criterion(DIABETES, {"type": kind, "term": term})])


@pytest.mark.parametrize("details", [["excluded"], {"note": "excluded"}])
def test_non_text_details_marked_excluded_still_fail_an_inclusion(details):
    concept = {"type": "medication", "term": "warfarin", "details": details}

    with pytest.raises(ValueError, match="marked excluded"):
        _generate(inclusion=[_criterion(DIABETES, concept)])


@pytest.mark.parametrize("details", [5, ["any dose"], None])
def test_non_text_details_without_the_marker_still_build(details):
    concept = {"type": "medication", "term": "warfarin", "details": details}

    sql, _ = _generate(inclusion=[_criterion(DIABETES, concept)])

    assert "medication_requests" in sql


# The prompt keeps a class as the term ("SSRIs", details "drug class — ...").
# Matched by name it finds no record: an inclusion zeroes, an exclusion removes
# no one (#455 expands classes).
@pytest.mark.parametrize("side", ["inclusion", "exclusion"])
@pytest.mark.parametrize(
    "details",
    ["drug class — RxNorm members include sertraline, fluoxetine", "Drug Class"],
)
def test_a_drug_class_medication_fails_the_request(details, side):
    concept = {"type": "medication", "term": SECRET, "details": details}

    with pytest.raises(ValueError) as raised:
        _generate(**{side: [_criterion(DIABETES, concept)]})

    assert "medication" in str(raised.value) and "drug class" in str(raised.value)
    assert SECRET not in str(raised.value)


def test_a_named_drug_is_not_a_drug_class():
    concept = {"type": "medication", "term": "metformin", "details": "any dose, not a classic"}

    sql, _ = _generate(inclusion=[_criterion(concept)])

    assert "medication_requests" in sql


@pytest.mark.parametrize(
    "concept",
    [
        {"type": "medication", "term": SECRET},
        {"type": "demographic", "term": "age", "details": SECRET},
        {"type": "demographic", "term": "race", "details": SECRET},
    ],
    ids=["built_term", "unparseable_age", "unbuildable_demographic"],
)
def test_info_and_warning_logs_carry_no_criterion_text(concept, caplog):
    caplog.set_level("INFO", logger="app.utils.sql_generator")
    try:
        _generate(inclusion=[_criterion(DIABETES, concept)])
    except ValueError:
        pass

    assert SECRET not in caplog.text


def test_a_criterion_that_builds_nothing_fails_next_to_one_that_does():
    with pytest.raises(ValueError, match="demographic"):
        _generate(
            inclusion=[
                _criterion(DIABETES),
                _criterion({"type": "demographic", "term": "race", "details": "white"}),
            ]
        )
