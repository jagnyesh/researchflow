"""#230: the per-request panels don't decide approval gates on their own.

Their buttons bypassed the workflow: "Approve Preview" wrote
current_state straight into the DB and called a no-op route_task;
"Reject Preview"/"Reject Delivery" updated rows without resuming the graph.
The Approvals queue (handle_approval_response) is the one decision path.
Drives the real show_preview_data_section through streamlit.testing, with a
DataDelivery row seeded in the test SQLite DB.
"""

import pytest
from streamlit.testing.v1 import AppTest


def _render(request_id, state):
    import uuid

    from app.database import ResearchRequest, get_db_session, init_db
    from app.database.models import DataDelivery
    from app.web_ui.admin_dashboard import run_async, show_preview_data_section

    async def seed():
        await init_db()
        async with get_db_session() as session:
            session.add(
                ResearchRequest(
                    id=request_id,
                    researcher_name="Synthetic Researcher",
                    researcher_email="r230@example.test",
                    initial_request="synthetic",
                    current_state=state,
                )
            )
            session.add(
                DataDelivery(
                    request_id=request_id,
                    preview_data={"demographics": [{"gender": "female"}]},
                    preview_qa_report={"overall_status": "failed", "checks": []},
                )
            )

    run_async(seed())
    show_preview_data_section(request_id, {"current_state": state})


@pytest.mark.parametrize("state", ["preview_qa", "preview_qa_review"])
def test_the_preview_panel_points_to_the_approvals_queue(state):
    import uuid

    request_id = f"REQ-230-{uuid.uuid4().hex[:8].upper()}"
    at = AppTest.from_function(_render, args=(request_id, state), default_timeout=30)
    at.run()

    assert not at.exception, at.exception
    labels = [b.label for b in at.button]
    assert not any("Preview" in label for label in labels), labels
    assert any("Approvals" in i.value for i in at.info), [i.value for i in at.info]


def test_the_dashboard_no_longer_offers_the_bypass_decisions():
    from app.services.approval_service import ApprovalService
    from app.web_ui import admin_dashboard

    # The DB-only decision paths the panels called; nothing else uses them.
    for name in ("approve_preview", "reject_preview", "reject_delivery", "approve_delivery"):
        assert not hasattr(ApprovalService, name), name
    assert not hasattr(admin_dashboard, "show_delivery_review_section")
