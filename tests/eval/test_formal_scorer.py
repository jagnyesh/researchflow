"""#239: the formal gold-set scorer.

A case passes only when the phenotype SQL executes and its patient set equals
the oracle's, compared inside Postgres (only counts come back; no patient id
leaves the database). An execution error is a fail, never a count; an oracle
that selects nobody makes the case vacuous, not a pass.

Live against HAPI (:5433), read-only. Requirements are passed in directly
here; the record/replay step that turns a request into them is separate.
"""

import json
import socket

import pytest

from tests.eval.formal_cases import FORMAL_CASES, FormalCase
from tests.eval.formal_harness import CaseScore, pass_at_1, score_case, write_jsonl


def _hapi_reachable():
    try:
        with socket.create_connection(("localhost", 5433), timeout=0.5):
            return True
    except OSError:
        return False


live = pytest.mark.skipif(not _hapi_reachable(), reason="HAPI Postgres (:5433) not running")

DIABETES = {
    "description": "diabetes mellitus",
    "concepts": [{"type": "condition", "term": "diabetes mellitus"}],
}


FEMALE = {
    "description": "female",
    "concepts": [{"type": "demographic", "term": "gender", "details": "female"}],
}
# A test-local oracle with patients in both the CI seed bundle (fixture-patient-d)
# and the local corpus, so these scorer tests are never vacuous; the seed gold
# cases' own oracles may select nobody on CI's 5-patient seed.
FEMALE_DM = FormalCase(
    id="scorer_female_diabetes_mellitus",
    request={},
    oracle_sql="""
        SELECT p.patient_id FROM sqlonfhir.patient_demographics p
        WHERE p.gender = 'female' AND EXISTS (
            SELECT 1 FROM sqlonfhir.condition_simple c
            WHERE c.patient_id = p.patient_id
              AND (c.code_text ILIKE '%diabetes mellitus%'
                   OR c.icd10_display ILIKE '%diabetes mellitus%'
                   OR c.snomed_display ILIKE '%diabetes mellitus%'))
    """,
    required_predicates=["gender = female", "condition: diabetes mellitus"],
)


def _case(**overrides):
    return FormalCase(**{**FEMALE_DM.__dict__, **overrides})


def _requirements(*criteria, exclusions=()):
    return {
        "inclusion_criteria": list(criteria),
        "exclusion_criteria": list(exclusions),
        "data_elements": ["demographics"],
        "time_period": {"start": None, "end": None},
    }


def test_every_seed_case_documents_its_format_and_signoff():
    assert len(FORMAL_CASES) == 2
    for case in FORMAL_CASES:
        assert case.oracle_sql.strip().upper().startswith("SELECT")
        assert "patient_id" in case.oracle_sql
        assert case.required_predicates
        # No case counts as gold until an informatician approves its oracle.
        assert case.signoff in ("pending", "approved")


@pytest.mark.asyncio
@pytest.mark.requires_services
@live
async def test_sql_matching_the_oracle_passes():
    result = await score_case(FEMALE_DM, _requirements(FEMALE, DIABETES))

    assert result.executed and not result.vacuous
    assert result.mismatch == 0 and result.passed
    assert result.sql_count == result.oracle_count > 0


@pytest.mark.asyncio
@pytest.mark.requires_services
@live
async def test_a_missing_predicate_fails_with_a_mismatch_count():
    # Drops the gender criterion: a superset of the oracle's cohort.
    result = await score_case(FEMALE_DM, _requirements(DIABETES))

    assert result.executed
    assert result.mismatch > 0 and not result.passed
    assert result.sql_count > result.oracle_count


@pytest.mark.asyncio
@pytest.mark.requires_services
@live
async def test_an_execution_error_fails_without_a_count():
    case = _case(oracle_sql="SELECT patient_id FROM sqlonfhir.no_such_view")

    result = await score_case(case, _requirements(DIABETES))

    assert not result.executed and not result.passed
    assert result.sql_count is None and result.mismatch is None
    assert result.error_ref and len(result.error_ref) == 12


@pytest.mark.asyncio
@pytest.mark.requires_services
@live
async def test_an_empty_oracle_is_vacuous_not_a_pass():
    case = _case(oracle_sql="SELECT p.patient_id FROM sqlonfhir.patient_demographics p WHERE false")
    nobody = {
        "description": "x",
        "concepts": [{"type": "condition", "term": "no-such-condition-zz"}],
    }

    result = await score_case(case, _requirements(nobody))

    assert result.executed and result.mismatch == 0
    assert result.vacuous and not result.passed


def test_pass_at_1_counts_vacuous_and_failed_cases_against_the_total():
    scores = [
        CaseScore(
            id="a",
            executed=True,
            passed=True,
            vacuous=False,
            sql_count=3,
            oracle_count=3,
            mismatch=0,
        ),
        CaseScore(
            id="b",
            executed=True,
            passed=False,
            vacuous=True,
            sql_count=0,
            oracle_count=0,
            mismatch=0,
        ),
        CaseScore(id="c", executed=False, passed=False, vacuous=False, error_ref="abcdef123456"),
    ]

    assert pass_at_1(scores) == pytest.approx(1 / 3)


def test_the_jsonl_evidence_carries_counts_only(tmp_path):
    score = CaseScore(
        id="a", executed=True, passed=True, vacuous=False, sql_count=3, oracle_count=3, mismatch=0
    )

    path = write_jsonl(
        [score], tmp_path / "evidence.jsonl", commit="deadbeef", batch_anchor_ts=None
    )

    [line] = path.read_text().splitlines()
    record = json.loads(line)
    assert record["id"] == "a" and record["commit"] == "deadbeef"
    assert set(record) >= {
        "passed",
        "vacuous",
        "sql_count",
        "oracle_count",
        "mismatch",
        "batch_anchor_ts",
    }
    assert all(
        not isinstance(v, (list, dict)) for v in record.values()
    ), "no patient sets in evidence"


@pytest.mark.asyncio
@pytest.mark.requires_services
@live
async def test_an_extra_predicate_fails_on_the_missing_patients():
    # One more criterion than the oracle: a strict subset of its cohort.
    over_65 = {
        "description": "> 65",
        "concepts": [{"type": "demographic", "term": "age", "details": "> 65"}],
    }

    result = await score_case(FEMALE_DM, _requirements(FEMALE, DIABETES, over_65))

    assert result.executed and not result.passed
    assert result.sql_count < result.oracle_count
    assert result.mismatch == result.oracle_count - result.sql_count


def test_both_seed_oracles_are_signed_off():
    # Approved by the repo owner on 2026-11-04 (#239).
    assert [c.signoff for c in FORMAL_CASES] == ["approved", "approved"]
