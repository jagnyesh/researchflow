"""#243: the formal gold set reports cost per passing phenotype SQL.

Each case's LLM cost is priced from its LangSmith trace in record mode and
stored in the fixture, so replay reports it. No API key here; replay runs
with whatever HAPI is up (a dead one only makes the cases fail).
"""

import json

import pytest

from tests.eval import formal_record
from tests.eval.formal_record import approved_cases, load_recording


def _write(path, entries):
    path.write_text(json.dumps(entries))
    return path


@pytest.mark.asyncio
async def test_replay_reports_each_cases_recorded_cost(tmp_path, monkeypatch):
    recorded = load_recording()
    fixture = _write(
        tmp_path / "rec.json",
        {
            c.id: {"requirements": recorded[c.id], "cost_usd": 0.001 * (i + 1)}
            for i, c in enumerate(approved_cases())
        },
    )
    monkeypatch.setattr(formal_record, "RECORDING", fixture)

    scores = await formal_record.replay(tmp_path / "evidence.jsonl")

    assert {s.id: s.cost_usd for s in scores} == {
        c.id: 0.001 * (i + 1) for i, c in enumerate(approved_cases())
    }


@pytest.mark.asyncio
async def test_record_stores_each_cases_trace_cost_in_the_fixture(tmp_path, monkeypatch):
    # Stubs stand in for the billed agent call and LangSmith; the live record
    # run in the PR's Testing Evidence checks the real trace pricing.
    recorded = load_recording()
    fixture = tmp_path / "rec.json"
    monkeypatch.setattr(formal_record, "RECORDING", fixture)

    async def agent(case):
        return recorded[case.id]

    priced = {}

    async def trace_costs(run_ids):
        priced.update(run_ids)
        return {case_id: 0.002 for case_id in run_ids}

    monkeypatch.setattr(formal_record, "_requirements_from_agent", agent)
    monkeypatch.setattr(formal_record, "_trace_costs", trace_costs)

    scores = await formal_record.record(tmp_path / "evidence.jsonl")

    ids = {c.id for c in approved_cases()}
    assert set(priced) == ids and len(set(priced.values())) == len(ids)
    assert {s.id: s.cost_usd for s in scores} == {i: 0.002 for i in ids}
    assert formal_record.load_costs(fixture) == {i: 0.002 for i in ids}
    assert formal_record.load_recording(fixture) == {i: recorded[i] for i in ids}


def _score(passed, cost):
    from tests.eval.formal_harness import CaseScore

    return CaseScore(id="c", executed=True, passed=passed, vacuous=False, cost_usd=cost)


def test_cost_per_passing_sql_divides_median_cost_by_pass_at_1():
    from tests.eval.formal_harness import cost_summary

    s = cost_summary([_score(True, 0.002), _score(False, 0.004), _score(True, 0.009)])

    assert s["median_cost_per_attempt_usd"] == 0.004
    assert s["cost_per_passing_sql_usd"] == round(0.004 / (2 / 3), 6)


def test_pass_at_1_of_zero_makes_cost_per_passing_sql_undefined():
    from tests.eval.formal_harness import cost_summary

    scores = [_score(False, 0.002), _score(False, 0.004)]
    s = cost_summary(scores)

    assert s["median_cost_per_attempt_usd"] == 0.003
    assert s["cost_per_passing_sql_usd"] is None
    assert "cost per passing SQL: undefined (Pass@1 = 0)" in formal_record.summary(scores)


def test_unpriced_attempts_report_as_unknown_not_zero():
    from tests.eval.formal_harness import cost_summary

    scores = [_score(True, None)]
    s = cost_summary(scores)

    assert s["median_cost_per_attempt_usd"] is None and s["cost_per_passing_sql_usd"] is None
    assert "cost per passing SQL: unknown" in formal_record.summary(scores)
