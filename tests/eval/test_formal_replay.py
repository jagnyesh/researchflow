"""#239: replay the recorded formal gold set, with no API key.

`python -m tests.eval.run_formal_record` sends each approved case's request
through the live Requirements Agent and records the structured requirements
it produced. This replays them through SQLGenerator and the scorer against
whatever HAPI is up (CI's seed or the local corpus). Oracles run same-run, so
nothing here depends on corpus size.

The gate here is the eval-gate rule: every approved case must have been
recorded and executed. A Pass@1 threshold is #244's.
"""

import socket

import pytest

from tests.eval.formal_cases import FORMAL_CASES
from tests.eval.formal_record import approved_cases, load_recording, replay


def _hapi_reachable():
    try:
        with socket.create_connection(("localhost", 5433), timeout=0.5):
            return True
    except OSError:
        return False


def test_every_approved_case_has_a_recording():
    recording = load_recording()

    assert {c.id for c in approved_cases()} <= set(recording), "re-run run_formal_record"


def test_only_approved_cases_are_scored():
    assert approved_cases() == [c for c in FORMAL_CASES if c.signoff == "approved"]


@pytest.mark.asyncio
@pytest.mark.requires_services
@pytest.mark.skipif(not _hapi_reachable(), reason="HAPI Postgres (:5433) not running")
async def test_replay_runs_every_approved_case(tmp_path):
    scores = await replay(evidence=tmp_path / "formal_gold_set.jsonl")

    assert len(scores) == len(approved_cases()) == 11
    # An expected-fail case may fail by erroring (its SQL can't run); it still
    # counts as a fail in Pass@1. Every other case must execute (#241).
    expected_fail = {c.id for c in approved_cases() if c.expected_fail}
    assert all(s.executed for s in scores if s.id not in expected_fail), [
        s.error_ref for s in scores
    ]
    assert not any(s.passed for s in scores if s.id in expected_fail)
    assert (tmp_path / "formal_gold_set.jsonl").read_text().count("\n") == 11


@pytest.mark.asyncio
@pytest.mark.requires_services
@pytest.mark.skipif(not _hapi_reachable(), reason="HAPI Postgres (:5433) not running")
async def test_a_pending_case_is_never_scored(tmp_path, monkeypatch):
    from dataclasses import replace

    from tests.eval import formal_record

    pending = replace(FORMAL_CASES[0], id="pending_case", signoff="pending")
    monkeypatch.setattr(formal_record, "FORMAL_CASES", [*FORMAL_CASES, pending])

    scores = await replay(evidence=tmp_path / "evidence.jsonl")

    assert "pending_case" not in {s.id for s in scores}


@pytest.mark.asyncio
@pytest.mark.requires_services
@pytest.mark.skipif(not _hapi_reachable(), reason="HAPI Postgres (:5433) not running")
async def test_the_anchor_covers_only_the_views_a_case_touches():
    from tests.eval.formal_record import touched_views

    views = touched_views(FORMAL_CASES[0], load_recording()[FORMAL_CASES[0].id])

    assert views == {"patient_demographics", "condition_simple"}


@pytest.mark.asyncio
async def test_recording_one_case_leaves_the_other_recordings_untouched(tmp_path, monkeypatch):
    # #142: adding a case records only that case (one billed agent run), not all of them.
    import json

    from tests.eval import formal_record

    fixture = tmp_path / "rec.json"
    original = formal_record.RECORDING.read_text()
    fixture.write_text(original)
    monkeypatch.setattr(formal_record, "RECORDING", fixture)
    target = approved_cases()[-1].id
    called = []

    async def agent(case):
        called.append(case.id)
        return load_recording()[case.id]

    async def trace_costs(run_ids):
        return {case_id: 0.005 for case_id in run_ids}

    monkeypatch.setattr(formal_record, "_requirements_from_agent", agent)
    monkeypatch.setattr(formal_record, "_trace_costs", trace_costs)

    scores = await formal_record.record(tmp_path / "evidence.jsonl", only=target)

    assert called == [target]
    before, after = json.loads(original), json.loads(fixture.read_text())
    assert {k: v for k, v in after.items() if k != target} == {
        k: v for k, v in before.items() if k != target
    }
    assert after[target] == {"requirements": before[target]["requirements"], "cost_usd": 0.005}
    assert {s.id for s in scores} == {c.id for c in approved_cases()}


def test_recording_an_unknown_case_fails_before_any_call():
    import asyncio

    from tests.eval import formal_record

    with pytest.raises(ValueError):
        asyncio.run(formal_record.record(None, only="no_such_case"))


def test_the_summary_lists_expected_fail_cases_with_their_reason():
    from tests.eval.formal_harness import CaseScore
    from tests.eval.formal_record import summary

    case = next(c for c in approved_cases() if c.expected_fail)
    other = next(c for c in approved_cases() if not c.expected_fail)
    scores = [
        CaseScore(id=case.id, executed=False, passed=False, vacuous=False),
        CaseScore(id=other.id, executed=True, passed=True, vacuous=False),
    ]

    text = summary(scores)

    assert "Pass@1: 0.50 (1/2)" in text  # expected-fail stays in the denominator
    assert f"{case.id}: EXPECTED-FAIL" in text and case.expected_fail in text
    assert f"{other.id}: PASS" in text

    scores[0].passed = True
    assert f"{case.id}: UNEXPECTED-PASS" in summary(scores)


def test_a_case_whose_sql_cant_be_generated_still_anchors_on_its_oracle():
    from tests.eval.formal_record import touched_views

    case = next(c for c in approved_cases() if c.id == "diabetes_mellitus_not_on_insulin")
    unbuildable = {
        "inclusion_criteria": [
            {
                "description": "diabetes mellitus",
                "concepts": [{"type": "condition", "term": "diabetes mellitus"}],
            }
        ],
        # An unsupported concept type: medications build since ADR 0036.
        "exclusion_criteria": [
            {"description": "insulin", "concepts": [{"type": "allergy", "term": "insulin"}]}
        ],
        "data_elements": ["demographics"],
        "time_period": {"start": None, "end": None},
    }
    from app.utils.sql_generator import SQLGenerator

    with pytest.raises(ValueError):
        SQLGenerator(use_materialized_views=True).generate_phenotype_sql(unbuildable)

    assert touched_views(case, unbuildable) == {
        "patient_demographics",
        "condition_simple",
        "medication_requests",
    }
