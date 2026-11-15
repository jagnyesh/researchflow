"""#434: the phenotype SQL reject dialog asks for the route as a control of its own.

Drives the real `display_approval_card` through streamlit.testing. The only
double is `handle_approval_response`, which would otherwise call the orchestrator;
what it receives is the dashboard's whole contribution to the decision.
"""

from streamlit.testing.v1 import AppTest

REVISION = "Reject for revision"
NOT_FEASIBLE = "Reject as not feasible"


def _render(approval_type, calls):
    from app.web_ui import admin_dashboard

    admin_dashboard.handle_approval_response = lambda *args: calls.append(args)
    approval = {
        "id": 7,
        "request_id": "REQ-TEST-0434",
        "approval_type": approval_type,
        "submitted_at": "2026-01-01T00:00:00",
        "submitted_by": "workflow",
        "timeout_at": None,
        "approval_data": {"sql_query": "SELECT 1"},
    }
    admin_dashboard.display_approval_card(approval, "reviewer@example.org", expanded=True)


def _open_reject_dialog(approval_type):
    calls = []
    at = AppTest.from_function(_render, args=(approval_type, calls), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    next(b for b in at.button if b.label == "Reject").click().run()
    assert not at.exception, at.exception
    return at, calls


def _confirm(at, reason):
    at.text_area(key="reject_reason_7").set_value(reason).run()
    next(b for b in at.button if b.label == "Confirm rejection").click().run()
    assert not at.exception, at.exception


def test_the_sql_reject_dialog_offers_the_two_routes_and_defaults_to_revision():
    at, _ = _open_reject_dialog("phenotype_sql")

    route = at.radio(key="reject_route_7")
    assert list(route.options) == [REVISION, NOT_FEASIBLE]
    assert route.value == REVISION


def test_a_revision_rejection_sends_the_route_and_leaves_the_note_alone():
    at, calls = _open_reject_dialog("phenotype_sql")

    _confirm(at, "This is not infeasible, just fix the join")

    assert calls == [
        (
            7,
            "reject",
            "reviewer@example.org",
            "This is not infeasible, just fix the join",
            {"rejection_route": "revision"},
        )
    ]


def test_a_not_feasible_rejection_sends_the_not_feasible_route():
    at, calls = _open_reject_dialog("phenotype_sql")
    at.radio(key="reject_route_7").set_value(NOT_FEASIBLE).run()

    _confirm(at, "Too few patients at this site")

    assert calls[0][4] == {"rejection_route": "not_feasible"}


def test_other_gates_have_no_route_control_and_send_no_route():
    at, calls = _open_reject_dialog("requirements")

    assert not at.radio
    _confirm(at, "Missing exclusion criteria")

    assert calls == [(7, "reject", "reviewer@example.org", "Missing exclusion criteria", {})]
