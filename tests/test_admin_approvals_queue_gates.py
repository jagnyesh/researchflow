"""#329: the Approvals queue shows the full-QA summary on a delivery card and
can filter to the preview-QA and delivery gates.

Drives the real ``display_approval_card`` and ``show_pending_approvals`` through
``streamlit.testing``. The delivery payload mirrors what
``ApprovalBridge._extract_approval_data("delivery", ...)`` writes, with
synthetic values only.
"""

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

DELIVERY_PAYLOAD = {
    "qa_report": {
        "overall_status": "passed",
        "checks": [
            {
                "check_name": "data_completeness",
                "passed": True,
                "severity": "info",
                "message": "All requested elements present",
            },
            {
                "check_name": "cohort_validation",
                "passed": False,
                "severity": "warning",
                "message": "Cohort 42 differs from estimate 30",
            },
        ],
        "issues": [],
        "recommendations": ["Spot-check the lab values before release"],
    },
    "overall_status": "passed",
    # The bridge embeds the whole data package; the card must not dump it.
    "data_package": {
        "cohort": ["synthetic-patient-id-1", "synthetic-patient-id-2"],
        "metadata": {
            "cohort_size": 42,
            "data_elements_extracted": ["conditions", "lab_results"],
            "data_elements_empty": ["medications"],
            "phi_level": "de-identified",
            "delivery_format": "CSV",
        },
    },
    "cohort_size": 42,
    "data_elements": ["conditions", "lab_results"],
    "message": "Full data extraction complete and QA passed. Ready for delivery approval.",
}


def _approval(approval_type, data):
    return {
        "id": 7,
        "request_id": "REQ-TEST-0001",
        "approval_type": approval_type,
        "submitted_at": "2026-01-01T00:00:00",
        "submitted_by": "workflow",
        "timeout_at": None,
        "approval_data": data,
    }


def _render_card(approval):
    from app.web_ui.admin_dashboard import display_approval_card

    display_approval_card(approval, "reviewer@example.org", expanded=True)


def _run_card(approval):
    at = AppTest.from_function(_render_card, args=(approval,), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def _text(at):
    parts = []
    for group in (at.markdown, at.subheader, at.error, at.warning, at.info, at.success, at.caption):
        parts.extend(str(e.value) for e in group)
    parts.extend(f"{m.label}={m.value}" for m in at.metric)
    return "\n".join(parts)


def test_delivery_card_shows_the_qa_summary_and_what_will_be_delivered():
    at = _run_card(_approval("delivery", DELIVERY_PAYLOAD))

    shown = _text(at)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Cohort size"] == "42"
    assert "passed" in shown
    assert "data_completeness" in shown
    assert "cohort_validation" in shown
    assert "Cohort 42 differs from estimate 30" in shown
    assert "conditions" in shown and "lab_results" in shown
    assert "de-identified" in shown and "CSV" in shown
    assert "Delivery approval" in shown


def test_delivery_card_does_not_dump_the_data_package():
    at = _run_card(_approval("delivery", DELIVERY_PAYLOAD))

    assert "synthetic-patient-id-1" not in _text(at)
    assert not at.json


def test_a_failed_qa_report_is_shown_as_failed():
    payload = dict(
        DELIVERY_PAYLOAD,
        overall_status="failed",
        qa_report=dict(DELIVERY_PAYLOAD["qa_report"], overall_status="failed"),
    )
    at = _run_card(_approval("delivery", payload))

    assert any("failed" in e.value for e in at.error)


def test_delivery_card_renders_when_the_payload_is_sparse():
    # The workflow's stub path writes no metadata and a dict-shaped checks field.
    sparse = {
        "qa_report": {"overall_status": "passed", "checks": {"completeness": {"passed": True}}},
        "overall_status": "passed",
        "data_package": {"total_patients": 150},
        "cohort_size": 0,
        "data_elements": [],
    }
    at = _run_card(_approval("delivery", sparse))

    assert "passed" in _text(at)


class _FakeService:
    calls = []

    def __init__(self, session):
        pass

    async def get_pending_approvals(self, approval_type=None):
        _FakeService.calls.append(approval_type)
        return [
            SimpleNamespace(
                id=1,
                request_id="REQ-TEST-0001",
                approval_type=approval_type or "delivery",
                submitted_at=datetime(2026, 1, 1),
                submitted_by="workflow",
                timeout_at=None,
                approval_data=DELIVERY_PAYLOAD,
            )
        ]


@asynccontextmanager
async def _no_session():
    yield None


def _render_queue():
    from app.web_ui.admin_dashboard import show_pending_approvals

    show_pending_approvals()


async def _no_telemetry():
    return []


def _patched():
    return (
        patch("app.web_ui.admin_dashboard.ApprovalService", _FakeService),
        patch("app.web_ui.admin_dashboard.get_db_session", _no_session),
        patch("app.web_ui.admin_dashboard.load_gate_telemetry", _no_telemetry),
    )


def _select_type(label):
    """Run the queue, pick ``label`` in the Type filter, return the type the service was asked for."""
    _FakeService.calls = []
    at = AppTest.from_function(_render_queue, default_timeout=30)
    p1, p2, p3 = _patched()
    with p1, p2, p3:
        at.run()
        assert not at.exception, at.exception
        options = list(at.selectbox(key="approval_type_filter").options)
        assert label in options, options
        at.selectbox(key="approval_type_filter").select(label).run()
        assert not at.exception, at.exception
    return _FakeService.calls[-1]


def test_type_filter_offers_preview_qa_and_selects_that_gate():
    assert _select_type("Preview QA") == "preview_qa"


def test_type_filter_offers_delivery_and_selects_that_gate():
    assert _select_type("Delivery") == "delivery"


def test_card_renders_what_the_bridge_really_writes_for_delivery():
    # Feed the card the bridge's own output, not a hand-copied fixture, so a
    # payload-shape change on either side fails here.
    from app.langchain_orchestrator.approval_bridge import ApprovalBridge

    state = {
        "qa_report": DELIVERY_PAYLOAD["qa_report"],
        "overall_status": "passed",
        "extracted_data_summary": DELIVERY_PAYLOAD["data_package"],
    }
    payload = ApprovalBridge()._extract_approval_data("delivery", state)

    at = _run_card(_approval("delivery", payload))

    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Cohort size"] == "42"
    assert "cohort_validation" in _text(at)
    assert "lab_results" in _text(at)
