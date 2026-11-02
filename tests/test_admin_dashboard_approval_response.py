"""The admin dashboard tells the reviewer when a decision is refused (#231).

Streamlit's ``st`` and the orchestrator are doubles; the facade raising
``ApprovalRefused`` for a refused decision is covered against the real DB in
``tests/test_approval_gate_resume.py``.
"""

from unittest.mock import MagicMock, patch

import app.web_ui.admin_dashboard as dashboard
from app.langchain_orchestrator.request_facade import ApprovalRefused


def test_a_refused_decision_is_a_warning_not_a_success():
    st = MagicMock()

    async def refuse(**kwargs):
        raise ApprovalRefused("Approval 7 is already approved")

    st.session_state.orchestrator.process_approval_response = refuse

    with patch.object(dashboard, "st", st):
        dashboard.handle_approval_response(7, "approve", "reviewer@example.test", None, None)

    st.warning.assert_called_once()
    assert "was not applied" in st.warning.call_args.args[0]
    st.success.assert_not_called()
    st.error.assert_not_called()
