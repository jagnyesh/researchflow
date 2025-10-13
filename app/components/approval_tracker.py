"""
Approval Tracker Component

Real-time monitoring of approval workflow status for research requests.
Displays pending approvals, workflow progress, and notifications.
"""

import streamlit as st
import httpx
from typing import Dict, Any, Optional
import asyncio
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ApprovalTracker:
    """Component for tracking approval workflow status"""

    def __init__(self, api_base_url: str = "http://localhost:8000"):
        self.api_base_url = api_base_url

    async def get_request_status(self, request_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current status of research request

        Args:
            request_id: Research request ID

        Returns:
            Dictionary with request status or None if not found
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.api_base_url}/research/{request_id}"
                )
                response.raise_for_status()
                return response.json()

        except httpx.HTTPError as e:
            logger.error(f"Failed to get request status: {e}")
            return None

    async def get_pending_approvals(self, request_id: str) -> list:
        """
        Get pending approvals for a request

        Args:
            request_id: Research request ID

        Returns:
            List of pending approval dictionaries
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.api_base_url}/approvals/request/{request_id}"
                )
                response.raise_for_status()

                approvals_data = response.json()
                approvals = approvals_data.get("approvals", [])

                # Filter for pending approvals
                return [a for a in approvals if a.get("status") == "pending"]

        except httpx.HTTPError as e:
            logger.error(f"Failed to get pending approvals: {e}")
            return []

    def render_approval_status(
        self,
        request_id: str,
        status_data: Dict[str, Any]
    ):
        """
        Render approval status card

        Args:
            request_id: Research request ID
            status_data: Status information from API
        """
        current_state = status_data.get("current_state", "unknown")
        current_agent = status_data.get("current_agent", "unknown")

        # Create status container
        st.markdown(f"""
<div style="
    background-color: #f0f8ff;
    border-left: 5px solid #1f77b4;
    padding: 15px;
    margin: 10px 0;
    border-radius: 5px;">
    <h3 style="margin-top: 0;">📋 Request {request_id}</h3>
    <p><strong>Current State:</strong> {current_state.replace('_', ' ').title()}</p>
    <p><strong>Current Agent:</strong> {current_agent}</p>
</div>
        """, unsafe_allow_html=True)

        # Show approval pipeline
        self._render_approval_pipeline(status_data)

        # Show state history
        with st.expander("View State History"):
            state_history = status_data.get("state_history", [])
            for entry in reversed(state_history[-10:]):  # Last 10 states
                state = entry.get("state", "unknown")
                timestamp = entry.get("timestamp", "")
                notes = entry.get("notes", "")
                st.text(f"{timestamp}: {state} {f'- {notes}' if notes else ''}")

    def _render_approval_pipeline(self, status_data: Dict[str, Any]):
        """Render approval pipeline visualization"""
        current_state = status_data.get("current_state", "")

        # Define workflow stages with icons
        stages = [
            ("new_request", "📝", "New Request"),
            ("requirements_gathering", "💬", "Requirements"),
            ("requirements_review", "⏸️", "Requirements Approval"),
            ("feasibility_validation", "📊", "Feasibility"),
            ("phenotype_review", "⚠️", "SQL Review (Critical)"),
            ("schedule_kickoff", "📅", "Scheduling"),
            ("extraction_approval", "🔐", "Extraction Approval"),
            ("data_extraction", "⚙️", "Extraction"),
            ("qa_validation", "✅", "QA"),
            ("qa_review", "⏸️", "QA Approval"),
            ("data_delivery", "📦", "Delivery"),
            ("delivered", "✅", "Delivered")
        ]

        st.markdown("### Workflow Progress")

        # Show pipeline as timeline
        cols = st.columns(len(stages))

        for idx, (state_key, icon, label) in enumerate(stages):
            with cols[idx]:
                # Check if this stage is complete, current, or pending
                if current_state == state_key:
                    # Current stage
                    st.markdown(f"""
<div style="text-align: center; background-color: #fff3cd; padding: 10px; border-radius: 5px;">
    <div style="font-size: 24px;">{icon}</div>
    <div style="font-size: 10px; font-weight: bold;">{label}</div>
    <div style="font-size: 8px; color: #856404;">◉ In Progress</div>
</div>
                    """, unsafe_allow_html=True)
                elif self._is_stage_complete(current_state, state_key, stages):
                    # Completed stage
                    st.markdown(f"""
<div style="text-align: center; background-color: #d4edda; padding: 10px; border-radius: 5px;">
    <div style="font-size: 24px;">✅</div>
    <div style="font-size: 10px;">{label}</div>
    <div style="font-size: 8px; color: #155724;">Complete</div>
</div>
                    """, unsafe_allow_html=True)
                else:
                    # Pending stage
                    st.markdown(f"""
<div style="text-align: center; background-color: #f8f9fa; padding: 10px; border-radius: 5px;">
    <div style="font-size: 24px; opacity: 0.3;">{icon}</div>
    <div style="font-size: 10px; opacity: 0.5;">{label}</div>
    <div style="font-size: 8px; color: #6c757d;">Pending</div>
</div>
                    """, unsafe_allow_html=True)

    def _is_stage_complete(
        self,
        current_state: str,
        stage_key: str,
        stages: list
    ) -> bool:
        """Check if a stage is complete based on current state"""
        try:
            current_idx = next(i for i, (key, _, _) in enumerate(stages) if key == current_state)
            stage_idx = next(i for i, (key, _, _) in enumerate(stages) if key == stage_key)
            return stage_idx < current_idx
        except StopIteration:
            return False

    async def poll_for_updates(
        self,
        request_id: str,
        poll_interval: int = 5,
        max_polls: int = 60
    ) -> Dict[str, Any]:
        """
        Poll for request status updates

        Args:
            request_id: Research request ID
            poll_interval: Seconds between polls
            max_polls: Maximum number of polls

        Returns:
            Final status dictionary
        """
        status_placeholder = st.empty()
        progress_bar = st.progress(0)

        for poll_count in range(max_polls):
            # Get current status
            status = await self.get_request_status(request_id)

            if not status:
                break

            # Update display
            with status_placeholder.container():
                current_state = status.get("current_state", "unknown")
                st.info(f"Current State: {current_state.replace('_', ' ').title()}")

                # Check if workflow is complete
                if current_state in ["delivered", "completed", "failed"]:
                    if current_state == "delivered":
                        st.success("✅ Data delivery complete!")
                    elif current_state == "failed":
                        st.error("❌ Workflow failed")
                    else:
                        st.success("✅ Workflow complete!")
                    break

            # Update progress bar
            progress_bar.progress((poll_count + 1) / max_polls)

            # Wait before next poll
            await asyncio.sleep(poll_interval)

        return status

    def render_pending_approvals(self, approvals: list):
        """
        Render list of pending approvals

        Args:
            approvals: List of pending approval dictionaries
        """
        if not approvals:
            st.info("No pending approvals")
            return

        st.markdown("### ⏸️ Pending Approvals")

        for approval in approvals:
            approval_type = approval.get("approval_type", "unknown")
            approval_id = approval.get("id")
            submitted_at = approval.get("submitted_at", "")
            submitted_by = approval.get("submitted_by", "unknown")

            # Determine urgency
            is_critical = approval_type == "phenotype_sql"
            urgency_color = "#dc3545" if is_critical else "#ffc107"
            urgency_label = "CRITICAL" if is_critical else "Pending"

            st.markdown(f"""
<div style="
    background-color: #fff;
    border-left: 5px solid {urgency_color};
    padding: 15px;
    margin: 10px 0;
    border-radius: 5px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
    <h4 style="margin-top: 0; color: {urgency_color};">{urgency_label}: {approval_type.replace('_', ' ').title()}</h4>
    <p><strong>Approval ID:</strong> {approval_id}</p>
    <p><strong>Submitted:</strong> {submitted_at}</p>
    <p><strong>By:</strong> {submitted_by}</p>
    <p><em>⏳ Awaiting informatician review...</em></p>
</div>
            """, unsafe_allow_html=True)

            # Show SQL for phenotype approvals
            if approval_type == "phenotype_sql":
                approval_data = approval.get("approval_data", {})
                sql_query = approval_data.get("sql_query", "")
                if sql_query:
                    with st.expander("View SQL Query"):
                        st.code(sql_query, language="sql")
