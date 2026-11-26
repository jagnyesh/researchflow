"""
#435 — the admin dashboard reads a request's kind from the state registry.

A request that ended in `error`, `qa_failed` or `not_feasible` must show the red dot
and count under Failed, not under In progress. The badge, the counters and the status
filter come from `app/database/workflow_states.py` (#432), so no state name is typed
into the dashboard.

The page runs for real through ``streamlit.testing``. Only its edges are stubbed, as in
``test_admin_dashboard_ui_365.py``. The stub orchestrator applies the same
``completed_at`` filter as ``LangGraphRequestFacade.get_all_active_requests``: a request
that ended in ``qa_failed`` or ``not_feasible`` has ``completed_at`` set, so the Overview
sees it only when it asks for completed requests. All data is synthetic.
"""

import ast
import inspect
import textwrap
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest

from app.database.workflow_states import StateKind, WorkflowState
from app.services.approval_service import ApprovalService
from app.services.cost_telemetry_service import CostSummary, CostTelemetryService
from app.web_ui import admin_dashboard

PAGE = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "admin_dashboard.py"

# `completed_at` is set for these today (persistence.py's terminal list).
_COMPLETED_STATES = {"complete", "not_feasible", "qa_failed", "human_review"}

# What the dashboard draws as a dot, by tone; the badge returns Streamlit colored text.
_TONE_OF_KIND = {
    StateKind.SUCCEEDED: ":green[●]",
    StateKind.FAILED: ":red[●]",
    StateKind.AWAITING_REVIEW: ":orange[●]",
    StateKind.IN_PROGRESS: ":blue[●]",
}


def _request(n: int, state: str) -> dict:
    return {
        "request_id": f"REQ-20261125-{n:08X}",
        "researcher_info": {"name": f"Synthetic Researcher {n}"},
        "current_state": state,
        "current_agent": None,
        "started_at": "2026-11-25T09:00:00",
        "completed_at": "2026-11-25T10:00:00" if state in _COMPLETED_STATES else None,
    }


class _Orchestrator:
    def __init__(self, states):
        self.requests = [_request(i, s) for i, s in enumerate(states, start=1)]
        self.asked_for_completed = []

    async def get_all_active_requests(self, include_completed: bool = False):
        self.asked_for_completed.append(include_completed)
        return [dict(r) for r in self.requests if include_completed or r["completed_at"] is None]


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _Session:
    async def execute(self, _query):
        return _Result([])


@asynccontextmanager
async def _db_session():
    yield _Session()


def _summary() -> CostSummary:
    return CostSummary(
        median_usd=0.007754,
        n_observed=30,
        cache_hit_rate=0.95,
        band_ceiling_usd=0.010080,
        gate_status="green",
    )


def _run(states) -> tuple[AppTest, _Orchestrator]:
    orchestrator = _Orchestrator(states)

    async def pending(self, approval_type=None, user_role=None):
        return []

    async def gates():
        return {}

    async def cost(self, n=30):
        return _summary()

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["orchestrator"] = orchestrator
    with ExitStack() as stack:
        stack.enter_context(patch.object(ApprovalService, "get_pending_approvals", pending))
        stack.enter_context(patch("app.database.get_db_session", _db_session))
        stack.enter_context(patch("app.services.gate_telemetry.load_gate_telemetry", gates))
        stack.enter_context(patch.object(CostTelemetryService, "get_formal_portal_cost_p50", cost))
        stack.enter_context(
            patch.object(CostTelemetryService, "get_exploratory_portal_cost_p50", cost)
        )
        stack.enter_context(
            patch(
                "app.sql_on_fhir.runner.mv_health_check.read_recent_health_records",
                lambda n=20: [],
            )
        )
        stack.enter_context(
            patch("app.sql_on_fhir.runner.mv_health_check.check_alarm", lambda v, n_runs=3: False)
        )
        stack.enter_context(patch("httpx.get", return_value=MagicMock(status_code=404)))
        at.run()
    assert not at.exception, at.exception
    return at, orchestrator


def _metrics(at: AppTest) -> dict:
    return {m.label: m.value for m in at.metric}


def _dots(at: AppTest) -> dict:
    """request_id -> the dot in its sidebar expander label."""
    out = {}
    for e in at.expander:
        if "REQ-20261125-" in e.label:
            dot, _, rest = e.label.partition(" ")
            out[rest.strip("`")] = dot
    return out


def test_error_and_qa_failed_requests_show_the_failed_dot_and_count_under_failed():
    at, _ = _run(["error", "qa_failed", "phenotype_review"])

    dots = _dots(at)
    assert dots["REQ-20261125-00000001"] == ":red[●]"
    assert dots["REQ-20261125-00000002"] == ":red[●]"
    assert dots["REQ-20261125-00000003"] == ":orange[●]"
    metrics = _metrics(at)
    assert metrics["Failed"] == "2"
    assert metrics["In progress"] == "1"
    assert metrics["Completed"] == "0"


def test_not_feasible_counts_once_under_failed():
    at, _ = _run(["not_feasible", "data_extraction", "complete"])

    metrics = _metrics(at)
    assert metrics["Failed"] == "1"
    assert metrics["In progress"] == "1"
    assert metrics["Completed"] == "1"
    assert _dots(at)["REQ-20261125-00000001"] == ":red[●]"


def test_the_overview_asks_for_completed_requests_or_it_never_sees_failures_that_end_the_run():
    at, orchestrator = _run(["qa_failed"])

    # Without include_completed the real facade drops the row (completed_at is set), so the
    # Failed counter stays 0 for exactly the requests this counter is for.
    assert all(orchestrator.asked_for_completed), orchestrator.asked_for_completed
    assert _metrics(at)["Requests"] == "1"


def test_states_the_registry_does_not_know_are_not_counted_as_in_progress():
    at, _ = _run(["delivered", "failed", "a_state_nothing_writes", "preview_qa"])

    metrics = _metrics(at)
    assert metrics["In progress"] == "1"
    assert metrics["Completed"] == "0"
    assert metrics["Failed"] == "0"
    assert metrics["Requests"] == "4"
    assert any("3" in c.value and "legacy" in c.value.lower() for c in at.caption), [
        c.value for c in at.caption
    ]


def test_the_status_filter_offers_every_state_the_workflow_writes():
    at, _ = _run(["error"])

    # The widget lists the registry's labels; the stored values are checked in the filter test.
    options = at.multiselect(key="status_filter").options
    for written in ("preview_qa_review", "qa_review", "not_feasible", "qa_failed", "error"):
        assert WorkflowState(written).info.label in options, (written, options)
    # Whatever the registry says is current, and nothing it calls legacy.
    expected = [s.info.label for s in WorkflowState if s.info.kind is not StateKind.LEGACY]
    assert options == expected
    for legacy in ("requirements_complete", "schedule_kickoff", "delivery_review", "delivered"):
        assert WorkflowState(legacy).info.label not in options, legacy


def test_filtering_on_error_keeps_only_the_error_request():
    at, _ = _run(["error", "phenotype_review"])

    at.multiselect(key="status_filter").set_value(["error"]).run()

    assert not at.exception, at.exception
    assert list(_dots(at)) == ["REQ-20261125-00000001"]


@pytest.mark.parametrize("state", list(WorkflowState), ids=lambda s: s.value)
def test_the_badge_follows_the_registry_kind_for_every_member(state):
    badge = admin_dashboard.get_status_badge(state.value)

    kind = state.info.kind
    if kind is StateKind.LEGACY:
        assert badge == ":gray[●]"
    elif state is WorkflowState.NEW_REQUEST:
        assert badge == ":gray[●]"
    else:
        assert badge == _TONE_OF_KIND[kind]


def test_the_badge_for_a_value_that_is_not_a_state_is_gray():
    assert admin_dashboard.get_status_badge("a_state_nothing_writes") == ":gray[●]"
    assert admin_dashboard.get_status_badge("") == ":gray[●]"
    assert admin_dashboard.get_status_badge(None) == ":gray[●]"


def test_the_three_readers_type_no_state_name():
    """The badge, the counters and the filter hold no state string of their own (#435)."""
    names = {s.value for s in WorkflowState}
    for fn in (
        admin_dashboard.get_status_badge,
        admin_dashboard.show_overview,
        admin_dashboard.show_requests_sidebar,
    ):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        # Only constants that sit in a comparison or a literal list, tuple or set: a dict key
        # such as the delivery check's "delivered" flag is not a state name.
        typed = {
            c.value
            for n in ast.walk(tree)
            if isinstance(n, (ast.Compare, ast.List, ast.Tuple, ast.Set))
            for c in ast.walk(n)
            if isinstance(c, ast.Constant) and c.value in names
        }
        assert not typed, (fn.__name__, typed)
