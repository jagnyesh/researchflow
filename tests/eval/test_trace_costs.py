"""#354: _trace_costs prices a trace only once LangSmith has ingested all of it.

The fake replaces langsmith.Client at the list_runs boundary. Each poll of a
trace's LLM leaves advances that trace one ingestion step, which is how a
mid-ingestion trace looks to the harness. No API key, no network.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import langsmith
import pytest

from app.services.cost_telemetry_service import _run_cost_usd
from tests.eval import harness

_T = datetime(2026, 11, 7, tzinfo=timezone.utc)


def _leaf(input_tokens, output_tokens):
    return SimpleNamespace(
        end_time=_T,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        metadata={"model": "claude-sonnet-4-6"},
        extra={},
    )


def _root(leaves, *, ended=True):
    return SimpleNamespace(
        end_time=_T if ended else None,
        total_tokens=sum(r.total_tokens for r in leaves),
    )


class _FakeClient:
    """`steps[trace_id]` is a list of (visible_leaves, root) ingestion states."""

    def __init__(self, steps):
        self._steps = steps
        self._poll = {t: 0 for t in steps}

    def _state(self, trace_id):
        states = self._steps[trace_id]
        return states[min(self._poll[trace_id], len(states) - 1)]

    def list_runs(self, *, trace_id, run_type=None, is_root=None, **_):
        # The harness reads leaves, then the root; step forward after the root
        # read so both calls in one poll see the same ingestion state.
        if is_root:
            _, root = self._state(trace_id)
            self._poll[trace_id] += 1
            return iter([root] if root is not None else [])
        leaves, _ = self._state(trace_id)
        return iter(list(leaves))


@pytest.fixture
def fake_langsmith(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(harness.asyncio, "sleep", no_sleep)

    def install(steps):
        monkeypatch.setattr(langsmith, "Client", lambda *a, **k: _FakeClient(steps))

    return install


def _cost(leaves):
    return round(sum(_run_cost_usd(r) for r in leaves), 6)


async def test_partially_ingested_trace_is_not_priced_from_a_subset(fake_langsmith):
    full = [_leaf(5000, 200), _leaf(3000, 400), _leaf(1000, 50)]
    fake_langsmith(
        {
            "t1": [
                # Poll 1: one leaf landed and finished; the root is still open.
                ([full[0]], _root(full[:1], ended=False)),
                # Poll 2: all leaves landed; the root closed with the full total.
                (full, _root(full)),
            ]
        }
    )

    costs = await harness._trace_costs({"case": "t1"})

    assert costs == {"case": _cost(full)}
    assert costs["case"] > _cost(full[:1])


async def test_root_closed_but_a_leaf_still_missing_waits_for_the_leaf(fake_langsmith):
    full = [_leaf(5000, 200), _leaf(3000, 400)]
    fake_langsmith(
        {
            "t1": [
                # Root total already counts a leaf the leaf query doesn't return yet.
                ([full[0]], _root(full)),
                (full, _root(full)),
            ]
        }
    )

    assert await harness._trace_costs({"case": "t1"}) == {"case": _cost(full)}


async def test_trace_that_never_completes_stays_unpriced_not_zero(fake_langsmith):
    full = [_leaf(5000, 200), _leaf(3000, 400)]
    fake_langsmith(
        {
            "done": [(full, _root(full))],
            "stuck_leaf": [([full[0]], _root(full))],
            "open_root": [(full, _root(full, ended=False))],
            "no_root": [(full, None)],
            # Leaves closed but usage not attached yet: 0 == 0 must not price at $0.
            "no_usage": [([_leaf(0, 0)], _root([_leaf(0, 0)]))],
        }
    )

    costs = await harness._trace_costs(
        {"a": "done", "b": "stuck_leaf", "c": "open_root", "d": "no_root", "e": "no_usage"},
        attempts=3,
    )

    assert costs == {"a": _cost(full)}


async def test_leaf_missing_from_both_leaves_and_rollup_is_not_priced(fake_langsmith):
    full = [_leaf(5000, 200), _leaf(3000, 400)]
    fake_langsmith(
        {
            "t1": [
                # Poll 1 looks complete: root closed, and its roll-up agrees with the
                # one leaf that landed, because the second leaf is in neither yet.
                ([full[0]], _root(full[:1])),
                (full, _root(full)),
            ]
        }
    )

    assert await harness._trace_costs({"case": "t1"}) == {"case": _cost(full)}


async def test_a_complete_looking_snapshot_must_repeat_before_it_is_priced(fake_langsmith):
    full = [_leaf(5000, 200), _leaf(3000, 400)]
    fake_langsmith({"t1": [([full[0]], _root(full[:1])), (full, _root(full))]})

    # Two polls, two different snapshots: neither has been seen twice.
    assert await harness._trace_costs({"case": "t1"}, attempts=2) == {}


async def test_usage_still_landing_on_the_same_leaf_is_not_priced_early(fake_langsmith):
    states = [_leaf(100, 0), _leaf(200, 0), _leaf(5000, 200)]
    fake_langsmith({"t1": [([r], _root([r])) for r in states]})

    # One leaf every poll; only its token count is still changing.
    assert await harness._trace_costs({"case": "t1"}) == {"case": _cost(states[-1:])}
