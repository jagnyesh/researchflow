"""
#365 — the admin dashboard's interface, driven through ``streamlit.testing``.

The whole page runs for real. Only its edges are stubbed: the orchestrator (seeded
into session state), the approvals table, the agent-executions query, gate
telemetry, LangSmith cost telemetry, the MV health log and the delivery API.
All data is synthetic.
"""

import re
from contextlib import ExitStack, asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest

from app.services.approval_service import ApprovalService
from app.services.cost_telemetry_service import CostSummary, CostTelemetryService

PAGE = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "admin_dashboard.py"

EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿⬀-⯿⏩-⏺]")

# Hostile text in every field a researcher or the LLM controls.
HOSTILE = "<img src=x onerror=alert(365)>"

REQUESTS = [
    {
        "request_id": "REQ-20261107-AAAA0001",
        "researcher_info": {"name": f"Synthetic Researcher {HOSTILE}"},
        "current_state": "phenotype_review",
        "current_agent": "phenotype_agent",
        "started_at": "2026-11-07T09:00:00",
    },
    {
        "request_id": "REQ-20261107-AAAA0002",
        "researcher_info": {"name": "Synthetic Researcher Two"},
        "current_state": "delivered",
        "current_agent": None,
        "started_at": "2026-11-06T09:00:00",
    },
]


def _sql_approval(approval_id: int, request_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=approval_id,
        request_id=request_id,
        approval_type="phenotype_sql",
        submitted_at=datetime(2026, 11, 7, 9, 30),
        submitted_by="langgraph_workflow",
        timeout_at=datetime.now() + timedelta(hours=1),
        approval_data={
            "initial_request": f"Women over 65 with diabetes {HOSTILE}",
            "structured_requirements": {
                "inclusion_criteria": [f"Age > 65 {HOSTILE}"],
                "exclusion_criteria": [],
                "data_elements": ["demographics"],
                "phi_level": "limited_dataset",
            },
            "phenotype_sql": "SELECT COUNT(*) FROM sqlonfhir.patient_simple",
            "estimated_cohort_size": 1284,
            "cohort_estimate": {"status": "ok"},
            "feasibility_score": 0.82,
            "data_availability": {"overall_availability": 0.9},
            "estimated_extraction_time_hours": 0.5,
            "auto_feasibility_assessment": "feasible",
            "warnings": [{"message": f"Synthetic warning {HOSTILE}"}],
            "recommendations": [f"Synthetic recommendation {HOSTILE}"],
        },
    )


class _Orchestrator:
    def __init__(self, fail: bool = False):
        self.fail = fail

    async def get_all_active_requests(self, include_completed: bool = False):
        if self.fail:
            raise ConnectionError("synthetic: database down")
        return [dict(r) for r in REQUESTS]


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _Session:
    """Answers fetch_agent_metrics: distinct agent ids, then executions."""

    def __init__(self):
        self.calls = 0

    async def execute(self, _query):
        self.calls += 1
        if self.calls == 1:
            return _Result([("phenotype_agent",)])
        started = datetime(2026, 11, 7, 9, 0)
        return _Result(
            [
                SimpleNamespace(
                    agent_id="phenotype_agent",
                    status="success",
                    started_at=started,
                    completed_at=started + timedelta(seconds=4),
                )
            ]
        )


@asynccontextmanager
async def _db_session():
    yield _Session()


def _summary(status: str) -> CostSummary:
    return CostSummary(
        median_usd=0.007754,
        n_observed=30,
        cache_hit_rate=0.95,
        band_ceiling_usd=0.010080,
        gate_status=status,
    )


def _run(approvals=(), fail_db: bool = False, health=None) -> AppTest:
    async def pending(self, approval_type=None, user_role=None):
        return list(approvals)

    async def gates():
        return {}

    async def formal(self, n=30):
        return _summary("green")

    async def exploratory(self, n=30):
        return _summary("red")

    not_delivered = MagicMock(status_code=404)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["orchestrator"] = _Orchestrator(fail=fail_db)
    with ExitStack() as stack:
        stack.enter_context(patch.object(ApprovalService, "get_pending_approvals", pending))
        stack.enter_context(patch("app.database.get_db_session", _db_session))
        stack.enter_context(patch("app.services.gate_telemetry.load_gate_telemetry", gates))
        stack.enter_context(
            patch.object(CostTelemetryService, "get_formal_portal_cost_p50", formal)
        )
        stack.enter_context(
            patch.object(CostTelemetryService, "get_exploratory_portal_cost_p50", exploratory)
        )
        stack.enter_context(
            patch(
                "app.sql_on_fhir.runner.mv_health_check.read_recent_health_records",
                lambda n=20: list(health or []),
            )
        )
        stack.enter_context(
            patch("app.sql_on_fhir.runner.mv_health_check.check_alarm", lambda v, n_runs=3: False)
        )
        stack.enter_context(patch("httpx.get", return_value=not_delivered))
        at.run()
    return at


def _visible_text(at: AppTest) -> list:
    texts = [m.value for m in at.markdown]
    texts += [c.value for c in at.caption]
    texts += [t.value for t in at.title]
    texts += [h.value for h in at.header] + [h.value for h in at.subheader]
    texts += [b.label for b in at.button]
    texts += [e.label for e in at.expander]
    texts += [t.label for t in at.tabs]
    texts += [m.label for m in at.metric] + [str(m.value) for m in at.metric]
    for kind in (at.info, at.success, at.warning, at.error):
        texts += [e.value for e in kind]
    for df in at.dataframe:
        texts += [str(v) for v in df.value.astype(str).to_numpy().ravel()]
        texts += [str(c) for c in df.value.columns]
    return texts


HEALTH = [
    {
        "ts": "2026-11-07T03:00:00",
        "view_name": "condition_diagnoses",
        "actual_count": 14832,
        "oracle_count": 14832,
        "delta_pct": 0.0,
        "status": "ok",
        "git_commit": "abc1234",
    }
]


def test_the_page_source_carries_no_emoji():
    found = sorted(set(EMOJI.findall(PAGE.read_text())))
    assert not found, found


def test_the_rendered_interface_carries_no_emoji():
    at = _run(approvals=[_sql_approval(1, "REQ-20261107-AAAA0001")], health=HEALTH)

    assert not at.exception, at.exception
    found = [t for t in _visible_text(at) if EMOJI.search(t)]
    assert not found, found


def test_user_and_llm_text_is_never_rendered_as_raw_html():
    # The health log's ts feeds the HTML "Data as of" stamp; it is file input, not ours.
    health = [dict(HEALTH[0], ts=HOSTILE)]
    at = _run(approvals=[_sql_approval(1, "REQ-20261107-AAAA0001")], health=health)

    assert not at.exception, at.exception
    html_blocks = [m.value for m in at.markdown if m.allow_html]
    assert any("Data as of" in h and "UTC" in h for h in html_blocks), html_blocks
    assert not [h for h in html_blocks if "<img" in h], html_blocks


def test_status_reads_as_dots_not_emoji_in_the_request_list():
    at = _run()

    labels = [e.label for e in at.expander if "REQ-20261107-AAAA000" in e.label]
    assert labels and all("●" in label for label in labels), labels


def test_an_empty_queue_says_so_quietly():
    at = _run(approvals=[])

    assert not at.exception, at.exception
    shown = [s.value for s in at.success] + [i.value for i in at.info]
    assert any("No pending approvals" in s for s in shown), shown
    assert not [t for t in _visible_text(at) if "!" in t and "<" not in t]


def test_only_the_first_sql_review_opens_expanded():
    approvals = [_sql_approval(i, f"REQ-20261107-BBBB000{i}") for i in (1, 2, 3)]
    at = _run(approvals=approvals)

    cards = [e for e in at.expander if "BBBB000" in e.label]
    assert [e.proto.expanded for e in cards] == [True, False, False], [e.label for e in cards]


def test_a_past_timeout_reads_as_overdue():
    approval = _sql_approval(1, "REQ-20261107-CCCC0001")
    approval.timeout_at = datetime.now() - timedelta(hours=3)
    at = _run(approvals=[approval])

    labels = [e.label for e in at.expander if "CCCC0001" in e.label]
    assert labels and "overdue" in labels[0] and ":red[●]" in labels[0], labels


def test_dollar_amounts_in_warnings_do_not_pair_into_latex():
    approval = _sql_approval(1, "REQ-20261107-DDDD0001")
    approval.approval_data["warnings"] = [{"message": "Costs $5"}, {"message": "and $6"}]
    at = _run(approvals=[approval])

    shown = " ".join(w.value for w in at.warning)
    assert "\\$5" in shown and "\\$6" in shown, shown


def test_a_sql_review_card_shows_the_sql_and_its_estimate():
    at = _run(approvals=[_sql_approval(1, "REQ-20261107-AAAA0001")])

    assert any("sqlonfhir.patient_simple" in c.value for c in at.code)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics.get("Estimated Cohort") == "1,284", metrics


def test_an_unreachable_database_is_an_error_not_a_crash():
    at = _run(fail_db=True)

    assert not at.exception, at.exception
    errors = [e.value for e in at.error]
    assert any("database isn't reachable" in e for e in errors), errors


def test_the_analytics_figures_are_labelled_illustrative():
    at = _run()

    shown = [c.value for c in at.caption] + [i.value for i in at.info]
    assert any("Illustrative" in s for s in shown), shown


@pytest.mark.parametrize("gate", ["green", "red", "gray"])
def test_cost_gate_states_render_without_emoji(gate):
    async def summary(self, n=30):
        return _summary(gate)

    with (
        patch.object(CostTelemetryService, "get_formal_portal_cost_p50", summary),
        patch.object(CostTelemetryService, "get_exploratory_portal_cost_p50", summary),
    ):
        at = AppTest.from_function(_render_cost, default_timeout=60)
        at.run()

    assert not at.exception, at.exception
    assert not [t for t in _visible_text(at) if EMOJI.search(t)]


def _render_cost():
    from unittest.mock import patch as _patch

    from app.web_ui.admin_dashboard import show_cost_telemetry

    with _patch(
        "app.sql_on_fhir.runner.mv_health_check.read_recent_health_records", lambda n=20: []
    ):
        show_cost_telemetry()
