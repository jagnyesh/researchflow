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

    assert len(scores) == len(approved_cases()) == 2
    assert all(s.executed for s in scores), [s.error_ref for s in scores]
    assert (tmp_path / "formal_gold_set.jsonl").read_text().count("\n") == 2
