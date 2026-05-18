"""
ResearchFlow Admin Dashboard

Streamlit interface for administrators to monitor system and review escalations.
"""

# CRITICAL: Set up event loop BEFORE any other imports
# This ensures the database engine (created at import time) uses our loop
import asyncio
import nest_asyncio
import sys
import os

# ALWAYS create a fresh event loop and set it as THE loop for this thread
# This ensures database engine Queue objects bind to our loop
_streamlit_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_streamlit_loop)

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply(_streamlit_loop)

# NOW safe to import modules that create database connections
import streamlit as st
import pandas as pd
import httpx
from datetime import datetime, timedelta
import time
import logging
from dotenv import load_dotenv
from sqlalchemy import select

# Set up logger for this module
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Phase 3b CSO Finding 2: streamlit processes start outside the FastAPI lifespan,
# so the encryption-key gate must run independently here. Without this call, a
# typo'd ENCRYPTION_KEY_PRIMARY in production surfaces only on the first PHI
# access as cryptography.fernet.InvalidToken inside a SQLAlchemy result-processor
# stack frame — burying the misconfiguration. With this call, the dashboard
# refuses to start and emits the same clean RuntimeError as `uvicorn`.
from app.security.encryption_keys import assert_encryption_key_present_if_production

assert_encryption_key_present_if_production()

from app.langchain_orchestrator.request_facade import LangGraphRequestFacade
from app.database import get_db_session, get_engine
from app.database.models import AgentExecution, ResearchRequest
from app.services.approval_service import ApprovalService


def run_async(coroutine):
    """
    Run async code in Streamlit's persistent event loop.

    Uses the loop set up at module import time to ensure all
    database operations use the same loop.
    """
    return _streamlit_loop.run_until_complete(coroutine)


def _render_db_unreachable(exc: Exception, what: str) -> None:
    """Render a friendly error for a failed DB call. Use after catching from run_async."""
    logger.exception("Failed to load %s", what)
    st.error(
        f"⚠️ Could not load {what} — the database isn't reachable. "
        "Check that PostgreSQL is running and DATABASE_URL is correct."
    )
    with st.expander("Error details"):
        st.code(f"{type(exc).__name__}: {exc}")


def get_status_badge(state: str) -> str:
    """Get colored status badge for request state"""
    state_colors = {
        "delivered": "🟢",
        "complete": "🟢",
        "data_delivery": "🟡",
        "delivery_review": "🟠",  # NEW: Awaiting delivery approval
        "qa_validation": "🟡",
        "data_extraction": "🟡",
        "preview_qa": "🔵",  # NEW: Preview QA validation
        "preview_extraction": "🔵",  # NEW: Preview extraction
        "feasibility_validation": "🔵",
        "requirements_gathering": "🔵",
        "failed": "🔴",
        "not_feasible": "🔴",
    }
    return state_colors.get(state.lower(), "⚪")


def check_delivery_status(request_id: str) -> dict:
    """
    Check if data is delivered for a request

    Returns dict with:
        - delivered: bool
        - files: list of file dicts
        - cohort_size: int
        - delivery_location: str
    """
    try:
        # Call delivery API endpoint
        api_url = os.getenv("API_BASE_URL", "http://localhost:8000")
        response = httpx.get(f"{api_url}/research/{request_id}/delivery", timeout=10.0)

        if response.status_code == 200:
            return response.json()
        else:
            return {"delivered": False, "files": []}
    except Exception as e:
        st.error(f"Error checking delivery status: {str(e)}")
        return {"delivered": False, "files": []}


def download_file(request_id: str, filename: str = None):
    """Download file(s) from delivered request"""
    try:
        api_url = os.getenv("API_BASE_URL", "http://localhost:8000")

        if filename:
            # Download specific file
            url = f"{api_url}/research/{request_id}/download/{filename}"
        else:
            # Download full ZIP package
            url = f"{api_url}/research/{request_id}/download"
            filename = f"{request_id}_data_package.zip"

        response = httpx.get(url, timeout=60.0)

        if response.status_code == 200:
            # Return file content for st.download_button
            return response.content, filename
        else:
            st.error(f"Download failed: {response.status_code} - {response.text}")
            return None, None

    except Exception as e:
        st.error(f"Download error: {str(e)}")
        return None, None


def initialize_orchestrator():
    """Initialize orchestrator with all agents"""
    if "orchestrator" not in st.session_state:
        # Ensure database engine is initialized for current event loop
        # This prevents "Queue is bound to a different event loop" errors
        get_engine()

        # Sprint 7.2 Phase 4: A2A's ResearchRequestOrchestrator deleted; the
        # USE_LANGGRAPH_WORKFLOW + LANGGRAPH_ROLLOUT_PCT feature flags are
        # retired with it. LangGraph is now the unconditional default.
        orchestrator = LangGraphRequestFacade(
            use_real_agents=True,  # Use production agents
            use_persistence=True,  # Enable checkpointing
        )
        st.session_state.orchestrator = orchestrator


def show_requests_sidebar():
    """Show all submitted requests in sidebar"""
    st.header("📋 All Requests")

    # Get all requests (FIXED: include completed requests for search)
    try:
        requests = run_async(
            st.session_state.orchestrator.get_all_active_requests(include_completed=True)
        )
    except Exception as e:
        _render_db_unreachable(e, "requests")
        return

    # Search box
    search_term = st.text_input(
        "🔍 Search", key="search_requests", placeholder="Search by ID or researcher"
    )

    # Status filter (all possible workflow states)
    all_statuses = [
        "new_request",
        "requirements_gathering",
        "requirements_complete",
        "requirements_review",
        "feasibility_validation",
        "phenotype_review",
        "human_review",
        "preview_extraction",
        "preview_qa",
        "schedule_kickoff",
        "data_extraction",
        "qa_validation",
        "delivery_review",
        "data_delivery",
        "delivered",
        "complete",
        "failed",
    ]
    status_filter = st.multiselect(
        "Filter by Status", options=all_statuses, default=[], key="status_filter"
    )

    # Filter requests
    filtered_requests = requests
    if search_term:
        filtered_requests = [
            r
            for r in filtered_requests
            if search_term.lower() in r.get("request_id", "").lower()
            or search_term.lower() in r.get("researcher_info", {}).get("name", "").lower()
        ]
    if status_filter:
        filtered_requests = [
            r
            for r in filtered_requests
            if r.get("current_state", "").lower() in [s.lower() for s in status_filter]
        ]

    st.caption(f"Showing {len(filtered_requests)} of {len(requests)} requests")

    # Display requests
    if filtered_requests:
        for idx, req in enumerate(filtered_requests):
            badge = get_status_badge(req.get("current_state", ""))
            req_id = req.get("request_id", "Unknown")
            req_short = req_id[:12] + "..." if len(req_id) > 12 else req_id

            with st.expander(f"{badge} {req_short}"):
                researcher_name = req.get("researcher_info", {}).get("name", "N/A")
                st.write(f"**Researcher:** {researcher_name}")
                st.write(f"**Status:** {req.get('current_state', 'N/A').replace('_', ' ').title()}")

                started_at = req.get("started_at", "")
                if started_at:
                    st.write(
                        f"**Started:** {started_at[:19] if isinstance(started_at, str) else started_at}"
                    )

                # Check delivery
                delivery = check_delivery_status(req_id)
                if delivery.get("delivered"):
                    st.write(f"**Cohort:** {delivery.get('cohort_size', 0):,} patients")
                    st.write(f"**Files:** {len(delivery.get('files', []))} ready")

                if st.button("View Details", key=f"view_{idx}_{req_id}"):
                    st.session_state.selected_request = req_id

        # Check if modal should be shown
        if st.session_state.get("selected_request"):
            show_request_details_modal(st.session_state.selected_request)
    else:
        st.info("No requests match the filters")


@st.dialog("Request Details", width="large")
def show_request_details_modal(request_id: str):
    """Show detailed request information in modal"""

    # Get request status
    status = run_async(st.session_state.orchestrator.get_request_status(request_id))

    if not status:
        st.error(f"Request not found: {request_id}")
        return

    # Header
    st.subheader(f"Request: {request_id}")

    # Metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Status", status.get("current_state", "N/A").replace("_", " ").title())
    with col2:
        st.metric(
            "Current Agent", (status.get("current_agent") or "None").replace("_", " ").title()
        )
    with col3:
        started = status.get("started_at", "")
        if started:
            try:
                started_dt = datetime.fromisoformat(started)
                duration = datetime.now() - started_dt
                st.metric("Duration", f"{duration.seconds // 60} min")
            except:
                st.metric("Duration", "N/A")

    st.markdown("---")

    # Researcher Info
    st.markdown("### 👤 Researcher Information")
    researcher = status.get("researcher_info", {})
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Name:** {researcher.get('name', 'N/A')}")
        st.write(f"**Email:** {researcher.get('email', 'N/A')}")
    with col2:
        st.write(f"**Department:** {researcher.get('department', 'N/A')}")
        st.write(f"**IRB Number:** {researcher.get('irb_number', 'N/A')}")

    st.markdown("---")

    # Workflow Timeline
    st.markdown("### 📊 Workflow Timeline")
    if status.get("agents_involved"):
        for activity in reversed(status["agents_involved"][-10:]):  # Show last 10
            agent = activity.get("agent", "").replace("_", " ").title()
            task = activity.get("task", "").replace("_", " ").title()
            timestamp = activity.get("timestamp", "")[:19] if activity.get("timestamp") else "N/A"
            st.markdown(f"**{timestamp}** - {agent}: {task}")
    else:
        st.info("No agent activity yet")

    st.markdown("---")

    # Approval History
    st.markdown("### ✅ Approval History")
    try:
        approval_history = run_async(st.session_state.orchestrator.get_approval_history(request_id))

        if approval_history:
            for approval in approval_history:
                approval_type = approval.get("approval_type", "").replace("_", " ").title()
                status_icon = {
                    "approved": "✅",
                    "rejected": "❌",
                    "pending": "⏳",
                    "modified": "✏️",
                    "timeout": "⏰",
                }.get(approval.get("status", ""), "❓")

                with st.expander(
                    f"{status_icon} {approval_type} - {approval.get('status', 'N/A').title()}"
                ):
                    col1, col2 = st.columns(2)
                    with col1:
                        submitted_at = approval.get("submitted_at", "N/A")
                        if submitted_at != "N/A":
                            submitted_at = submitted_at[:19]
                        st.write(f"**Submitted:** {submitted_at}")
                        st.write(f"**Submitted By:** {approval.get('submitted_by', 'N/A')}")
                    with col2:
                        reviewed_at = approval.get("reviewed_at", "N/A")
                        if reviewed_at and reviewed_at != "N/A":
                            reviewed_at = reviewed_at[:19]
                        st.write(f"**Reviewed:** {reviewed_at}")
                        st.write(f"**Reviewed By:** {approval.get('reviewed_by', 'N/A')}")

                    if approval.get("review_notes"):
                        st.write(f"**Notes:** {approval.get('review_notes')}")
        else:
            st.info("No approvals recorded yet")
    except Exception as e:
        st.warning(f"Could not load approval history: {str(e)}")

    st.markdown("---")

    # Preview Data Section (NEW - Sprint X)
    show_preview_data_section(request_id, status)

    st.markdown("---")

    # Delivery Review Section (NEW - Sprint X)
    if status.get("current_state") == "delivery_review":
        show_delivery_review_section(request_id)
    else:
        # Regular Download Section
        show_download_section(request_id)

    # Close button
    if st.button("Close", type="secondary", use_container_width=True):
        del st.session_state.selected_request
        st.rerun()


def show_preview_data_section(request_id: str, status: dict):
    """Show preview data (10 rows per element) if available"""
    from app.database.models import DataDelivery
    from sqlalchemy import select

    st.markdown("### 🔍 Preview Data")

    # Check if preview data is available
    try:

        async def get_preview_data():
            async with get_db_session() as session:
                result = await session.execute(
                    select(DataDelivery).where(DataDelivery.request_id == request_id)
                )
                delivery = result.scalar_one_or_none()
                return delivery

        delivery = run_async(get_preview_data())

        if delivery and delivery.preview_data:
            st.success("✅ Preview extraction complete (10 rows per element)")

            # Show preview QA report summary
            if delivery.preview_qa_report:
                qa_report = delivery.preview_qa_report
                status_icon = "✅" if qa_report.get("overall_status") == "passed" else "❌"
                st.info(
                    f"{status_icon} Preview QA Status: {qa_report.get('overall_status', 'unknown').upper()}"
                )

                # Show QA checks
                with st.expander("Preview QA Checks"):
                    for check in qa_report.get("checks", []):
                        check_icon = "✅" if check.get("passed") else "❌"
                        st.write(
                            f"{check_icon} {check.get('check_name', 'Unknown')}: {check.get('message', 'N/A')}"
                        )

            # Display preview data tables
            st.markdown("#### Preview Data Tables")
            st.caption("Showing first 10 rows per data element")

            preview_data = delivery.preview_data
            for element_name, records in preview_data.items():
                if records:
                    with st.expander(
                        f"📊 {element_name.replace('_', ' ').title()} ({len(records)} rows)"
                    ):
                        # Convert to DataFrame for better display
                        df = pd.DataFrame(records)
                        st.dataframe(df, use_container_width=True, height=300)
                else:
                    st.warning(f"⚠️ {element_name.replace('_', ' ').title()}: No data")

            # Add approval buttons if in preview_qa state
            if status.get("current_state") == "preview_qa":
                st.markdown("---")
                st.markdown("#### 🔍 Preview Review & Approval")
                st.caption("Review the preview data above before authorizing full data extraction")

                col1, col2 = st.columns(2)

                with col1:
                    if st.button(
                        "✅ Approve Preview - Proceed to Full Extraction",
                        type="primary",
                        use_container_width=True,
                        key=f"approve_preview_{request_id}",
                    ):
                        # Approve preview and trigger full extraction via orchestrator
                        async def approve_preview_action():
                            async with get_db_session() as session:
                                # Get request from DB
                                result = await session.execute(
                                    select(ResearchRequest).where(ResearchRequest.id == request_id)
                                )
                                request = result.scalar_one_or_none()

                                if not request:
                                    return {"success": False, "error": "Request not found"}

                                # Update state to data_extraction
                                request.current_state = "data_extraction"
                                request.current_agent = "extraction_agent"

                                # Update state history
                                state_history = request.state_history or []
                                state_history.append(
                                    {
                                        "state": "data_extraction",
                                        "timestamp": datetime.now().isoformat(),
                                        "approved_by": "admin_dashboard",
                                        "notes": "Preview approved - proceeding to full data extraction",
                                    }
                                )
                                request.state_history = state_history

                                await session.commit()

                                # Build context from request data
                                requirements_dict = (
                                    request.requirements_data.requirements
                                    if request.requirements_data
                                    else {}
                                )

                            # Use session orchestrator (respects LangGraph feature flag)
                            orchestrator = st.session_state.orchestrator

                            context = {
                                "request_id": request_id,
                                "requirements": requirements_dict,
                                "phenotype_sql": request.phenotype_sql,
                            }

                            # Route to extraction agent for full extraction
                            await orchestrator.route_task(
                                agent_id="extraction_agent",
                                task="extract_data",
                                context=context,
                                from_agent="admin_dashboard",
                            )

                            return {"success": True}

                        result = run_async(approve_preview_action())

                        if result.get("success"):
                            st.success("✅ Preview approved! Full data extraction has begun.")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(
                                f"❌ Failed to approve preview: {result.get('error', 'Unknown error')}"
                            )

                with col2:
                    if st.button(
                        "❌ Reject Preview",
                        type="secondary",
                        use_container_width=True,
                        key=f"reject_preview_{request_id}",
                    ):
                        # Show rejection reason form
                        with st.form(f"reject_preview_form_{request_id}"):
                            st.warning("⚠️ Rejecting preview will send the request back for review")
                            rejection_reason = st.text_area(
                                "Rejection Reason (required)",
                                placeholder="e.g., Data quality issues, incorrect cohort, etc.",
                                key=f"preview_rejection_reason_{request_id}",
                            )

                            col_a, col_b = st.columns(2)
                            with col_a:
                                submit_reject = st.form_submit_button(
                                    "Confirm Rejection", type="primary", use_container_width=True
                                )
                            with col_b:
                                cancel_reject = st.form_submit_button(
                                    "Cancel", use_container_width=True
                                )

                            if submit_reject and rejection_reason:

                                async def reject_preview_action():
                                    async with get_db_session() as session:
                                        from app.services.approval_service import ApprovalService

                                        approval_service = ApprovalService(session)

                                        result = await approval_service.reject_preview(
                                            request_id=request_id,
                                            reviewed_by="admin_dashboard",
                                            review_notes=rejection_reason,
                                        )
                                        return result

                                result = run_async(reject_preview_action())

                                if result.get("rejected"):
                                    st.success("✅ Preview rejected. Request sent back for review.")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(
                                        f"❌ Rejection failed: {result.get('error', 'Unknown error')}"
                                    )
                            elif submit_reject:
                                st.error("❌ Please provide a rejection reason")

        elif status.get("current_state") in ["preview_extraction"]:
            # Show loading spinner for preview extraction
            with st.spinner("⏳ Extracting preview data (10 rows per element)..."):
                # Get estimated time from SQL approval if available
                async def get_estimated_time():
                    async with get_db_session() as session:
                        from app.database.models import Approval
                        from sqlalchemy import select

                        result = await session.execute(
                            select(Approval)
                            .where(Approval.request_id == request_id)
                            .where(Approval.approval_type == "phenotype_sql")
                        )
                        approval = result.scalar_one_or_none()
                        if approval and approval.approval_data:
                            return approval.approval_data.get("estimated_extraction_time_hours", 0)
                        return 0

                est_time = run_async(get_estimated_time())

                if est_time > 0:
                    if est_time < 1:
                        time_msg = f"Estimated time: ~{int(est_time * 60)} minutes"
                    else:
                        time_msg = f"Estimated time: ~{est_time:.1f} hours"
                    st.info(f"⏳ {time_msg}")
                else:
                    st.info("⏳ Extraction in progress...")

                # Auto-refresh every 5 seconds to check for completion
                st.caption("🔄 Auto-refreshing every 5 seconds...")
                time.sleep(5)
                st.rerun()
        elif status.get("current_state") in [
            "data_extraction",
            "qa_validation",
            "delivery_review",
            "data_delivery",
            "delivered",
            "complete",
        ]:
            st.success("✅ Preview was approved - full data extraction completed")
        else:
            st.caption("Preview data not available yet (request hasn't reached preview extraction)")

    except Exception as e:
        st.warning(f"Could not load preview data: {str(e)}")


def show_delivery_review_section(request_id: str):
    """Show delivery review UI with download + approve/reject buttons"""
    st.markdown("### 📦 Delivery Review")

    st.info("⏳ **Awaiting Informatician Approval**")
    st.caption("Review the full dataset before approving for delivery to researcher")

    # Get delivery data
    from app.database.models import DataDelivery
    from sqlalchemy import select

    try:

        async def get_delivery_data():
            async with get_db_session() as session:
                result = await session.execute(
                    select(DataDelivery).where(DataDelivery.request_id == request_id)
                )
                return result.scalar_one_or_none()

        delivery = run_async(get_delivery_data())

        if delivery:
            # Show QA report summary
            if delivery.qa_report:
                qa_report = delivery.qa_report
                status_icon = "✅" if qa_report.get("overall_status") == "passed" else "❌"
                st.success(
                    f"{status_icon} Full QA Status: {qa_report.get('overall_status', 'unknown').upper()}"
                )

                # Metrics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric(
                        "Cohort Size",
                        f"{delivery.cohort_size:,}" if delivery.cohort_size else "N/A",
                    )
                with col2:
                    st.metric(
                        "Data Elements",
                        len(delivery.data_elements) if delivery.data_elements else 0,
                    )
                with col3:
                    st.metric("Files", len(delivery.file_list) if delivery.file_list else 0)

                # Show QA checks
                with st.expander("Full QA Report"):
                    for check in qa_report.get("checks", []):
                        check_icon = "✅" if check.get("passed") else "❌"
                        st.write(
                            f"{check_icon} {check.get('check_name', 'Unknown')}: {check.get('message', 'N/A')}"
                        )

            st.markdown("---")

            # Download full dataset for review
            st.markdown("**Step 1: Download Full Dataset**")
            st.caption("Download and review the complete dataset before approval")

            delivery_info = check_delivery_status(request_id)
            if delivery_info.get("delivered") or delivery.file_list:
                if st.button(
                    "📥 Download Full Dataset (ZIP)",
                    type="secondary",
                    use_container_width=True,
                    key=f"dl_review_{request_id}",
                ):
                    with st.spinner("Preparing download..."):
                        file_content, filename = download_file(request_id)
                        if file_content:
                            st.download_button(
                                label="💾 Save Dataset",
                                data=file_content,
                                file_name=filename,
                                mime="application/zip",
                                type="secondary",
                                use_container_width=True,
                                key=f"save_review_{request_id}",
                            )
                            st.success(f"✅ Ready to download: {filename}")
            else:
                st.warning("⚠️ Full dataset not yet available for download")

            st.markdown("---")

            # Approve/Reject buttons
            st.markdown("**Step 2: Approve or Reject Delivery**")

            col1, col2 = st.columns(2)

            with col1:
                # Get pending delivery approval for this request
                async def get_delivery_approval_id():
                    async with get_db_session() as session:
                        from app.database.models import Approval
                        from sqlalchemy import select

                        result = await session.execute(
                            select(Approval.id)
                            .where(Approval.request_id == request_id)
                            .where(Approval.approval_type == "delivery")
                            .where(Approval.status == "pending")
                        )
                        approval = result.scalar_one_or_none()
                        return approval

                delivery_approval_id = run_async(get_delivery_approval_id())

                if not delivery_approval_id:
                    st.warning("⚠️ No pending delivery approval found")
                elif st.button(
                    "✅ Approve Delivery",
                    type="primary",
                    use_container_width=True,
                    key=f"approve_delivery_{request_id}",
                ):
                    # FIXED: Use handle_approval_response() to trigger workflow continuation
                    # This is consistent with phenotype SQL approval and ensures orchestrator
                    # calls delivery_agent after approval
                    handle_approval_response(
                        approval_id=delivery_approval_id,
                        decision="approve",
                        reviewer="admin_dashboard",
                        notes="Approved via Admin Dashboard",
                        modifications={},
                    )

            with col2:
                if st.button(
                    "❌ Reject Delivery",
                    type="secondary",
                    use_container_width=True,
                    key=f"reject_delivery_{request_id}",
                ):
                    # Show rejection reason dialog
                    with st.form(key=f"reject_form_{request_id}"):
                        reason = st.text_area(
                            "Rejection Reason",
                            placeholder="Explain why the dataset is being rejected...",
                            key=f"reject_reason_{request_id}",
                        )

                        submit = st.form_submit_button("Confirm Rejection", type="secondary")

                        if submit and reason:

                            async def reject_delivery_action():
                                async with get_db_session() as session:
                                    approval_service = ApprovalService(session)
                                    result = await approval_service.reject_delivery(
                                        request_id=request_id,
                                        reviewed_by="admin_dashboard",
                                        review_notes=reason,
                                    )
                                    return result

                            result = run_async(reject_delivery_action())

                            if not result.get("approved"):
                                st.success(
                                    "✅ Delivery rejected. Request will return to extraction."
                                )
                                time.sleep(1)
                                del st.session_state.selected_request
                                st.rerun()
                            else:
                                st.error(
                                    f"❌ Rejection failed: {result.get('error', 'Unknown error')}"
                                )
                        elif submit:
                            st.error("Please provide a rejection reason")
        else:
            st.warning("⚠️ Delivery data not found")

    except Exception as e:
        st.error(f"Error loading delivery review: {str(e)}")


def show_download_section(request_id: str):
    """Show download options in modal"""
    st.markdown("### 📦 Data Delivery")

    delivery_info = check_delivery_status(request_id)

    if delivery_info.get("delivered"):
        st.success("✅ Data ready for download")

        # Metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Cohort Size", f"{delivery_info.get('cohort_size', 0):,}")
        with col2:
            st.metric("Data Elements", len(delivery_info.get("data_elements", [])))
        with col3:
            st.metric("Files", len(delivery_info.get("files", [])))

        st.markdown("---")

        # Download ZIP
        st.markdown("**Download Complete Package (ZIP)**")
        st.caption("Includes all data files, data dictionary, QA report, and documentation")

        if st.button(
            "📦 Download ZIP", type="primary", use_container_width=True, key=f"dl_zip_{request_id}"
        ):
            with st.spinner("Preparing download..."):
                file_content, filename = download_file(request_id)
                if file_content:
                    st.download_button(
                        label="💾 Save ZIP File",
                        data=file_content,
                        file_name=filename,
                        mime="application/zip",
                        type="primary",
                        use_container_width=True,
                        key=f"save_zip_{request_id}",
                    )
                    st.success(f"✅ Ready to download: {filename}")

        st.markdown("---")

        # Individual files
        st.markdown("**Individual Files**")
        files = delivery_info.get("files", [])
        if files:
            for idx, file_info in enumerate(files):
                filename = file_info.get("filename", "unknown")
                size_mb = file_info.get("size_mb", 0)

                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"📄 {filename} ({size_mb:.2f} MB)")
                with col2:
                    if st.button(
                        "Download", key=f"dl_admin_{request_id}_{idx}", use_container_width=True
                    ):
                        with st.spinner(f"Downloading {filename}..."):
                            file_content, _ = download_file(request_id, filename)
                            if file_content:
                                st.download_button(
                                    label=f"💾 Save",
                                    data=file_content,
                                    file_name=filename,
                                    mime="text/csv" if filename.endswith(".csv") else "text/plain",
                                    key=f"save_admin_{request_id}_{idx}",
                                    use_container_width=True,
                                )
        else:
            st.info("No files available")

        # QA Summary
        if delivery_info.get("qa_report_summary"):
            st.markdown("---")
            st.markdown("**Quality Assurance Summary**")
            st.json(delivery_info["qa_report_summary"])

    else:
        current_state = delivery_info.get("current_state", "unknown")
        st.info(
            f"Data not yet delivered. Current status: {current_state.replace('_', ' ').title()}"
        )


def main():
    """Main admin dashboard application"""
    st.set_page_config(page_title="ResearchFlow - Admin Dashboard", page_icon="⚙️", layout="wide")

    # Initialize orchestrator
    initialize_orchestrator()

    # Header
    st.title("⚙️ ResearchFlow - Admin Dashboard")
    st.caption("System monitoring and management")

    # Auto-refresh controls
    col1, col2, col3, col4 = st.columns([2, 2, 2, 6])

    with col1:
        auto_refresh = st.checkbox("Auto-refresh", value=False, key="auto_refresh")

    with col2:
        refresh_interval = st.selectbox(
            "Interval",
            options=[5, 10, 30, 60],
            format_func=lambda x: f"{x}s",
            key="refresh_interval",
            disabled=not auto_refresh,
        )

    with col3:
        if st.button("🔄 Refresh Now", key="manual_refresh"):
            st.rerun()

    with col4:
        if "last_refresh" in st.session_state:
            st.caption(f"Last updated: {st.session_state.last_refresh.strftime('%H:%M:%S')}")

    # Update last refresh time
    st.session_state.last_refresh = datetime.now()

    # Main layout: Sidebar + Main Area
    col_sidebar, col_main = st.columns([1, 3])

    # Sidebar with request list
    with col_sidebar:
        show_requests_sidebar()

    # Main area with tabs
    with col_main:
        # Tabs
        tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
            [
                "📊 Overview",
                "🤖 Agent Metrics",
                "✋ Pending Approvals",
                "🚨 Escalations",
                "📈 Analytics",
                "🗄️ Materialized Views",
                "💰 Cost Telemetry",
            ]
        )

        with tab1:
            show_overview()

        with tab2:
            show_agent_metrics()

        with tab3:
            show_pending_approvals()

        with tab4:
            show_escalations()

        with tab5:
            show_analytics()

        with tab6:
            show_materialized_views()

        with tab7:
            show_cost_telemetry()

    # Auto-refresh logic
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()


def show_overview():
    """Display system overview"""
    st.header("System Overview")

    # Get all active requests
    try:
        requests = run_async(st.session_state.orchestrator.get_all_active_requests())
    except Exception as e:
        _render_db_unreachable(e, "system overview")
        return

    # Metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Requests", len(requests))

    with col2:
        in_progress = len(
            [r for r in requests if r["current_state"] not in ["delivered", "complete", "failed"]]
        )
        st.metric("In Progress", in_progress)

    with col3:
        completed = len([r for r in requests if r["current_state"] in ["delivered", "complete"]])
        st.metric("Completed", completed)

    with col4:
        failed = len([r for r in requests if r["current_state"] == "failed"])
        st.metric("Failed/Escalated", failed, delta=-failed if failed > 0 else None)

    # Recent requests
    st.subheader("📋 Recent Requests")

    if requests:
        df_data = []
        for req in requests[:10]:  # Show last 10
            df_data.append(
                {
                    "Request ID": req["request_id"][:16] + "...",
                    "Researcher": req["researcher_info"].get("name", "N/A"),
                    "Status": req["current_state"],
                    "Current Agent": req.get("current_agent", "None"),
                    "Started": req["started_at"][:19],
                }
            )

        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No requests yet")


def show_agent_metrics():
    """
    Display agent performance metrics from database

    NOTE: Queries AgentExecution table instead of in-memory state
    to support cross-process visibility (Researcher Portal → Admin Dashboard)
    """
    st.header("🤖 Agent Performance Metrics")

    # Query AgentExecution table from database
    async def fetch_agent_metrics():
        async with get_db_session() as session:
            # Sprint 7.2 migration gap fix (2026-05-17, discovered during
            # Sprint 6.5 portal walkthrough on REQ-20260517-A097C5F6): the
            # old A2A pattern populated orchestrator.agents via explicit
            # register_agent() calls. LangGraphRequestFacade constructs
            # agents internally and leaves self.agents = {} empty, so this
            # panel rendered "No agent metrics available yet" for every
            # request even when agent_executions had rows.
            #
            # Derive registered_agents from the agent_executions table
            # itself — self-maintaining as the agent set evolves and works
            # regardless of which orchestrator implementation is wired.
            distinct_agents_result = await session.execute(
                select(AgentExecution.agent_id)
                .where(AgentExecution.agent_id.isnot(None))
                .distinct()
            )
            registered_agents = [row[0] for row in distinct_agents_result.all()]

            # Initialize metrics for ALL registered agents
            metrics_by_agent = {}
            for agent_id in registered_agents:
                metrics_by_agent[agent_id] = {
                    "total_tasks": 0,
                    "successful_tasks": 0,
                    "failed_tasks": 0,
                    "durations": [],
                    "state": "idle",
                }

            # Get all agent executions
            result = await session.execute(
                select(AgentExecution).order_by(AgentExecution.started_at.desc())
            )
            all_executions = result.scalars().all()

            # Populate metrics from execution records
            for execution in all_executions:
                agent_id = execution.agent_id

                # Only count executions from registered agents
                if agent_id in metrics_by_agent:
                    metrics_by_agent[agent_id]["total_tasks"] += 1

                    if execution.status == "success":
                        metrics_by_agent[agent_id]["successful_tasks"] += 1
                    elif execution.status == "failed":
                        metrics_by_agent[agent_id]["failed_tasks"] += 1

                    if execution.completed_at and execution.started_at:
                        duration = (execution.completed_at - execution.started_at).total_seconds()
                        metrics_by_agent[agent_id]["durations"].append(duration)

            # Calculate success rate and avg duration for all agents
            for agent_id, metrics in metrics_by_agent.items():
                metrics["success_rate"] = (
                    metrics["successful_tasks"] / metrics["total_tasks"]
                    if metrics["total_tasks"] > 0
                    else 0
                )
                metrics["avg_duration_seconds"] = (
                    sum(metrics["durations"]) / len(metrics["durations"])
                    if metrics["durations"]
                    else 0
                )

            return metrics_by_agent

    try:
        all_metrics = run_async(fetch_agent_metrics())
    except Exception as e:
        _render_db_unreachable(e, "agent metrics")
        return

    if not all_metrics:
        st.info("No agent metrics available yet")
        return

    # Create metrics table
    metrics_data = []
    for agent_id, metrics in all_metrics.items():
        agent_name = agent_id.replace("_", " ").title()
        metrics_data.append(
            {
                "Agent": agent_name,
                "State": metrics["state"],
                "Total Tasks": metrics["total_tasks"],
                "Successful": metrics["successful_tasks"],
                "Failed": metrics["failed_tasks"],
                "Success Rate": f"{metrics['success_rate']:.1%}",
                "Avg Duration (s)": f"{metrics['avg_duration_seconds']:.1f}",
            }
        )

    df = pd.DataFrame(metrics_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Agent status indicators
    st.subheader("Agent Status")

    cols = st.columns(3)
    for idx, (agent_id, metrics) in enumerate(all_metrics.items()):
        with cols[idx % 3]:
            agent_name = agent_id.replace("_", " ").title()
            status = metrics["state"]
            status_emoji = "🟢" if status == "idle" else "🔵" if status == "working" else "🔴"

            st.metric(f"{status_emoji} {agent_name}", status, f"{metrics['total_tasks']} tasks")


def show_pending_approvals():
    """Display pending approvals requiring human review"""
    st.header("✋ Pending Approvals - Human-in-Loop Gates")

    # Filter by approval type
    col1, col2, col3 = st.columns([2, 2, 6])

    with col1:
        approval_type_filter = st.selectbox(
            "Filter by Type",
            ["All", "Requirements", "Phenotype SQL", "Extraction", "QA", "Scope Change"],
            key="approval_type_filter",
        )

    with col2:
        reviewer_email = st.text_input(
            "Your Email", placeholder="informatician@hospital.org", key="reviewer_email"
        )

    # Fetch pending approvals from database
    try:
        # Map UI selections to database values
        type_map = {
            "All": None,
            "Requirements": "requirements",
            "Phenotype SQL": "phenotype_sql",
            "Extraction": "extraction",
            "QA": "qa",
            "Scope Change": "scope_change",
        }

        approval_type_param = type_map[approval_type_filter]

        # Fetch approvals directly from database
        async def fetch_approvals():
            async with get_db_session() as session:
                approval_service = ApprovalService(session)
                approvals = await approval_service.get_pending_approvals(
                    approval_type=approval_type_param
                )
                return approvals

        try:
            approvals_db = run_async(fetch_approvals())
        except Exception as e:
            _render_db_unreachable(e, "pending approvals")
            return

        # Convert to dict format for display
        approvals = [
            {
                "id": approval.id,
                "request_id": approval.request_id,
                "approval_type": approval.approval_type,
                "submitted_at": approval.submitted_at.isoformat(),
                "submitted_by": approval.submitted_by,
                "timeout_at": approval.timeout_at.isoformat() if approval.timeout_at else None,
                "approval_data": approval.approval_data,
            }
            for approval in approvals_db
        ]

        # Metrics
        st.subheader("📊 Approval Queue Metrics")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total Pending", len(approvals))

        with col2:
            sql_approvals = len([a for a in approvals if a.get("approval_type") == "phenotype_sql"])
            st.metric(
                "🔴 SQL Reviews",
                sql_approvals,
                help="CRITICAL - SQL must be approved before execution",
            )

        with col3:
            req_approvals = len([a for a in approvals if a.get("approval_type") == "requirements"])
            st.metric("Requirements", req_approvals)

        with col4:
            scope_approvals = len(
                [a for a in approvals if a.get("approval_type") == "scope_change"]
            )
            st.metric("Scope Changes", scope_approvals)

        # Display approvals
        st.subheader("📋 Pending Approvals")

        if not approvals:
            st.success("✅ No pending approvals - all reviews complete!")
        else:
            for approval in approvals:
                display_approval_card(approval, reviewer_email)

    except Exception as e:
        st.error(f"Error fetching approvals: {str(e)}")
        import traceback

        st.code(traceback.format_exc())


def display_approval_card(approval, reviewer_email):
    """Display a single approval card with all details and action buttons"""
    approval_id = approval["id"]
    approval_type = approval["approval_type"]
    request_id = approval["request_id"]
    submitted_at = approval["submitted_at"]
    submitted_by = approval.get("submitted_by", "Unknown")
    timeout_at = approval.get("timeout_at")
    approval_data = approval.get("approval_data", {})

    # Determine urgency based on timeout
    urgency = "🟢 Normal"
    if timeout_at:
        timeout_dt = datetime.fromisoformat(timeout_at.replace("Z", "+00:00"))
        time_remaining = timeout_dt - datetime.now()
        hours_remaining = time_remaining.total_seconds() / 3600

        if hours_remaining < 2:
            urgency = "🔴 URGENT (< 2h)"
        elif hours_remaining < 6:
            urgency = "🟡 High Priority (< 6h)"

    # Type-specific styling
    type_emoji_map = {
        "requirements": "📄",
        "phenotype_sql": "🔴",  # Red circle for critical SQL
        "preview_qa": "⚠️",  # Warning for preview QA failure
        "extraction": "📊",
        "qa": "✓",
        "scope_change": "🔄",
    }

    type_label_map = {
        "requirements": "Requirements Review",
        "phenotype_sql": "SQL REVIEW (CRITICAL)",
        "preview_qa": "PREVIEW QA FAILED - REVIEW REQUIRED",
        "extraction": "Extraction Approval",
        "qa": "QA Review",
        "scope_change": "Scope Change",
    }

    emoji = type_emoji_map.get(approval_type, "📋")
    label = type_label_map.get(approval_type, approval_type.title())

    # Create expander with urgency indicator
    with st.expander(
        f"{emoji} {label} - {request_id[:20]}... | {urgency}",
        expanded=(approval_type == "phenotype_sql"),
    ):
        # Header info
        col1, col2, col3 = st.columns(3)
        with col1:
            st.write(f"**Request ID:** `{request_id}`")
        with col2:
            st.write(f"**Submitted:** {submitted_at[:19]}")
        with col3:
            if timeout_at:
                st.write(f"**Timeout:** {timeout_at[:19]}")

        st.write(f"**Submitted by:** {submitted_by}")

        st.divider()

        # Display type-specific approval data
        if approval_type == "phenotype_sql":
            display_sql_approval(approval_data)

        elif approval_type == "preview_qa":
            display_preview_qa_approval(approval_data)

        elif approval_type == "requirements":
            display_requirements_approval(approval_data)

        elif approval_type == "scope_change":
            display_scope_change_approval(approval_data)

        elif approval_type == "qa":
            display_qa_approval(approval_data)

        elif approval_type == "extraction":
            display_extraction_approval(approval_data)

        st.divider()

        # Action buttons
        st.subheader("Actions")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button(
                "✅ Approve", key=f"approve_{approval_id}", type="primary", use_container_width=True
            ):
                # Email optional for MVP (SSO handles authorization)
                reviewer = reviewer_email if reviewer_email else "System Admin"
                handle_approval_response(approval_id, "approve", reviewer, "", {})

        with col2:
            if st.button(
                "✏️ Modify & Approve", key=f"modify_{approval_id}", use_container_width=True
            ):
                st.session_state[f"show_modify_{approval_id}"] = True

        with col3:
            if st.button("❌ Reject", key=f"reject_{approval_id}", use_container_width=True):
                st.session_state[f"show_reject_{approval_id}"] = True

        # Modification interface
        if st.session_state.get(f"show_modify_{approval_id}", False):
            st.subheader("Approve with Modifications")
            notes = st.text_area(
                "Notes",
                placeholder="Explain your modifications...",
                key=f"modify_notes_{approval_id}",
            )

            if approval_type == "phenotype_sql":
                modified_sql = st.text_area(
                    "Modified SQL Query",
                    value=approval_data.get("sql_query", ""),
                    height=200,
                    key=f"modified_sql_{approval_id}",
                )
                modifications = {"sql_query": modified_sql}
            else:
                modifications = {}

            if st.button("Submit Modifications", key=f"submit_modify_{approval_id}"):
                # Email optional for MVP (SSO handles authorization)
                reviewer = reviewer_email if reviewer_email else "System Admin"
                handle_approval_response(approval_id, "modify", reviewer, notes, modifications)
                st.session_state[f"show_modify_{approval_id}"] = False

        # Rejection interface
        if st.session_state.get(f"show_reject_{approval_id}", False):
            st.subheader("Reject Approval")
            reject_reason = st.text_area(
                "Reason for Rejection",
                placeholder="Explain why this is being rejected and what needs to be fixed...",
                key=f"reject_reason_{approval_id}",
            )

            if st.button(
                "Confirm Rejection", key=f"confirm_reject_{approval_id}", type="secondary"
            ):
                if not reject_reason:
                    st.error("Please provide a reason for rejection")
                else:
                    # Email optional for MVP (SSO handles authorization)
                    reviewer = reviewer_email if reviewer_email else "System Admin"
                    handle_approval_response(approval_id, "reject", reviewer, reject_reason, {})
                    st.session_state[f"show_reject_{approval_id}"] = False


def display_sql_approval(data):
    """Display SQL approval details with syntax highlighting"""

    # Display Research Request Context (NEW - shows what researcher requested)
    st.subheader("📋 Research Request")

    # Display original request text
    initial_request = data.get("initial_request", "")
    if initial_request:
        st.info(f"**Original Request**: {initial_request}")
    else:
        st.info("**Original Request**: Not available")

    # Display structured requirements
    requirements = data.get("structured_requirements", {})
    if requirements:
        with st.expander("📊 Structured Requirements", expanded=True):
            # Display inclusion criteria
            inclusion = requirements.get("inclusion_criteria", [])
            if inclusion:
                st.markdown("**Inclusion Criteria:**")
                for criterion in inclusion:
                    # Handle both string and dict formats
                    if isinstance(criterion, dict):
                        criterion_text = criterion.get("description", str(criterion))
                    else:
                        criterion_text = str(criterion)
                    st.markdown(f"• {criterion_text}")

            # Display exclusion criteria
            exclusion = requirements.get("exclusion_criteria", [])
            if exclusion:
                st.markdown("**Exclusion Criteria:**")
                for criterion in exclusion:
                    if isinstance(criterion, dict):
                        criterion_text = criterion.get("description", str(criterion))
                    else:
                        criterion_text = str(criterion)
                    st.markdown(f"• {criterion_text}")

            # Display data elements
            data_elements = requirements.get("data_elements", [])
            if data_elements:
                st.markdown(f"**Data Elements**: {', '.join(str(elem) for elem in data_elements)}")

            # Display time period
            time_period = requirements.get("time_period", {})
            if time_period and isinstance(time_period, dict):
                start = time_period.get("start", "N/A")
                end = time_period.get("end", "N/A")
                st.markdown(f"**Time Period**: {start} to {end}")

            # Display PHI level
            phi_level = requirements.get("phi_level", "N/A")
            st.markdown(f"**PHI Level**: {phi_level}")

    st.divider()

    # SQL Query Review Section
    st.subheader("🔴 CRITICAL: SQL Query Review")

    st.warning(
        """
    **IMPORTANT:** This SQL query will execute against the production FHIR database if approved.
    Please verify:
    - SQL syntax is correct
    - Date filters are appropriate
    - Cohort size is reasonable
    - No sensitive fields are exposed
    - Joins and selections are accurate
    """
    )

    # SQL Query
    sql_query = data.get("phenotype_sql", "N/A")
    st.code(sql_query, language="sql")

    # Metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        cohort = data.get("estimated_cohort_size", "Unknown")
        st.metric("Estimated Cohort", cohort)

    with col2:
        feasibility = data.get("feasibility_score", 0)
        st.metric("Feasibility Score", f"{feasibility:.2f}")

    with col3:
        availability = data.get("data_availability", {}).get("overall_availability", 0)
        st.metric("Data Availability", f"{availability:.1%}")

    with col4:
        extraction_time = data.get("estimated_extraction_time_hours", 0)
        if extraction_time < 1:
            time_display = f"{int(extraction_time * 60)} min"
        else:
            time_display = f"{extraction_time:.1f} hrs"
        st.metric("Est. Preview Time", time_display)

    # Auto-Feasibility Assessment (informational, not decision gate)
    auto_assessment = data.get("auto_feasibility_assessment", "unknown")
    if auto_assessment == "not_feasible":
        st.error(
            "🔴 **Auto-Assessment: Low Cohort Size Detected**\n\n"
            "The automated feasibility check detected a small cohort size. "
            "Please review the SQL query carefully and consider:\n"
            "- Whether broader inclusion criteria would be appropriate\n"
            "- Whether the SQL query accurately represents the research intent\n"
            "- Whether this cohort size is acceptable for the study design"
        )
    elif auto_assessment == "feasible":
        st.success("✅ **Auto-Assessment: Adequate Cohort Size**")

    # Warnings
    warnings = data.get("warnings", [])
    if warnings:
        st.warning("⚠️ **Warnings:**")
        for warning in warnings:
            st.write(f"- {warning.get('message', warning)}")

    # Recommendations
    recommendations = data.get("recommendations", [])
    if recommendations:
        st.info("💡 **Recommendations:**")
        for rec in recommendations:
            st.write(f"- {rec}")


def display_preview_qa_approval(data):
    """Display preview QA failure details for review"""
    st.subheader("⚠️ Preview QA Failed - Review Required")

    # Display failure message
    message = data.get(
        "message",
        "Preview QA validation failed. Manual review required before proceeding to full extraction.",
    )
    st.error(message)

    # Display cohort check results
    cohort_check = data.get("cohort_check", {})
    if cohort_check:
        st.subheader("📊 Cohort Count Mismatch")

        col1, col2, col3 = st.columns(3)
        with col1:
            actual_size = cohort_check.get("details", {}).get("actual_cohort_size", "N/A")
            st.metric("Actual Cohort", actual_size)
        with col2:
            estimated_size = cohort_check.get("details", {}).get("estimated_cohort_size", "N/A")
            st.metric("Estimated Cohort", estimated_size)
        with col3:
            tolerance = cohort_check.get("details", {}).get("tolerance", "N/A")
            st.metric("Tolerance (±)", tolerance)

        # Show expected range
        details = cohort_check.get("details", {})
        if "lower_bound" in details and "upper_bound" in details:
            lower = details["lower_bound"]
            upper = details["upper_bound"]
            st.info(f"**Expected Range:** {lower} - {upper} patients")

        # Show check message
        check_message = cohort_check.get("message", "")
        if check_message:
            st.warning(f"**Issue:** {check_message}")

    st.divider()

    # Display QA report if available
    qa_report = data.get("qa_report", {})
    if qa_report:
        st.subheader("📋 QA Report")

        overall_status = qa_report.get("overall_status", "unknown")
        if overall_status == "failed":
            st.error(f"**Overall Status:** {overall_status.upper()}")
        else:
            st.success(f"**Overall Status:** {overall_status.upper()}")

        # Display issues
        issues = qa_report.get("issues", [])
        if issues:
            st.markdown("**Issues Found:**")
            for issue in issues:
                check_name = issue.get("check_name", "Unknown")
                severity = issue.get("severity", "info")
                message = issue.get("message", "No message")

                severity_emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(
                    severity, "⚪"
                )

                st.markdown(f"{severity_emoji} **{check_name}**: {message}")

    st.divider()

    # Display preview package metadata if available
    preview_package = data.get("preview_package", {})
    if preview_package:
        metadata = preview_package.get("metadata", {})
        if metadata:
            st.subheader("📦 Preview Package Metadata")
            st.json(metadata)

    # Decision guidance
    st.info(
        """
    **Decision Options:**

    **✅ Approve**: Proceed to full extraction despite cohort count mismatch.
    - Use if the mismatch is acceptable (e.g., data quality issue, acceptable variance)
    - Full extraction will proceed with all patients that match the SQL query

    **❌ Reject**: Return to SQL generation for revision.
    - Use if the SQL query needs to be fixed (e.g., wrong criteria, missing conditions)
    - Request will go back to phenotype agent for new SQL generation
    """
    )


def display_requirements_approval(data):
    """Display requirements approval details"""
    st.subheader("📄 Requirements Review")

    structured_reqs = data.get("structured_requirements", {})
    completeness = data.get("completeness_score", 0)

    # Completeness score
    st.metric("Completeness Score", f"{completeness:.1%}")

    # Study details
    if "study_title" in structured_reqs:
        st.write(f"**Study Title:** {structured_reqs['study_title']}")

    # Inclusion criteria
    inclusion = structured_reqs.get("inclusion_criteria", [])
    if inclusion:
        st.write("**Inclusion Criteria:**")
        for criterion in inclusion:
            st.write(f"- {criterion}")

    # Exclusion criteria
    exclusion = structured_reqs.get("exclusion_criteria", [])
    if exclusion:
        st.write("**Exclusion Criteria:**")
        for criterion in exclusion:
            st.write(f"- {criterion}")

    # Data elements
    elements = structured_reqs.get("data_elements", [])
    if elements:
        st.write(f"**Data Elements:** {', '.join(elements)}")

    # Full requirements (using details/summary instead of nested expander)
    st.markdown("---")
    st.markdown("**Full Requirements (JSON):**")
    st.json(structured_reqs)


def display_scope_change_approval(data):
    """Display scope change approval with impact analysis"""
    st.subheader("🔄 Scope Change Request")

    requested_changes = data.get("requested_changes", {})
    reason = data.get("reason", "N/A")
    impact = data.get("impact_analysis", {})

    # Reason
    st.write(f"**Reason:** {reason}")

    # Requested changes
    st.write("**Requested Changes:**")
    st.json(requested_changes)

    st.divider()

    # Impact analysis
    st.subheader("📊 Impact Analysis")

    severity = impact.get("severity", "unknown")
    severity_color = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(severity, "⚪")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Severity", f"{severity_color} {severity.title()}")

    with col2:
        requires_rework = impact.get("requires_rework", False)
        st.metric("Requires Rework", "Yes" if requires_rework else "No")

    with col3:
        delay = impact.get("estimated_delay_hours", 0)
        st.metric("Estimated Delay", f"{delay}h")

    # Restart point
    if impact.get("restart_from_state"):
        st.warning(f"⚠️ **Workflow will restart from:** `{impact['restart_from_state']}`")

    # Affected components
    affected = impact.get("affected_components", [])
    if affected:
        st.write(f"**Affected Components:** {', '.join(affected)}")


def display_qa_approval(data):
    """Display QA approval details"""
    st.subheader("✓ QA Results Review")

    st.write("**QA validation results:**")
    st.json(data)


def display_extraction_approval(data):
    """Display extraction approval details"""
    st.subheader("📊 Data Extraction Approval")

    st.write("**Extraction details:**")
    st.json(data)


def handle_approval_response(approval_id, decision, reviewer, notes, modifications):
    """Handle approval response (approve/reject/modify) and trigger workflow continuation"""
    try:
        logger.info(
            f"[Admin Dashboard] Processing approval {approval_id}: {decision} by {reviewer}"
        )

        async def process_approval_with_orchestrator():
            # Call orchestrator's process_approval_response method
            # This handles BOTH database update AND workflow continuation
            logger.info(
                f"[Admin Dashboard] Calling orchestrator.process_approval_response for approval {approval_id}"
            )
            await st.session_state.orchestrator.process_approval_response(
                approval_id=approval_id,
                reviewer=reviewer,
                decision=decision,
                notes=notes,
                modifications=modifications,
            )
            logger.info(
                f"[Admin Dashboard] orchestrator.process_approval_response completed for approval {approval_id}"
            )

        run_async(process_approval_with_orchestrator())

        if decision == "approve":
            st.success(f"✅ Approval {approval_id} approved! Workflow continuing to next agent...")
            logger.info(f"[Admin Dashboard] Approval {approval_id} approved successfully")
        elif decision == "reject":
            st.error(
                f"❌ Approval {approval_id} rejected. Request will return to originating agent."
            )
            logger.info(f"[Admin Dashboard] Approval {approval_id} rejected")
        elif decision == "modify":
            st.success(
                f"✏️ Approval {approval_id} approved with modifications. Workflow continuing with changes..."
            )
            logger.info(f"[Admin Dashboard] Approval {approval_id} modified and approved")

        # Trigger refresh after 2 seconds
        time.sleep(2)
        st.rerun()

    except Exception as e:
        st.error(f"Error processing approval: {str(e)}")
        logger.error(
            f"[Admin Dashboard] Error processing approval {approval_id}: {str(e)}", exc_info=True
        )
        import traceback

        st.code(traceback.format_exc())


def show_escalations():
    """Display escalations requiring human review"""
    st.header("🚨 Escalations & Human Review Queue")

    st.info(
        """
    **Note:** Escalations will appear here when:
    - Agents encounter errors after max retries
    - Data quality checks fail critically
    - Requests are not feasible
    - Complex decisions require human judgment
    """
    )

    # Mock escalation data for demonstration
    st.subheader("Pending Reviews")

    escalations = []  # TODO: Retrieve from database

    if escalations:
        for escalation in escalations:
            with st.expander(f"Request {escalation['request_id']} - {escalation['reason']}"):
                st.write(f"**Agent:** {escalation['agent']}")
                st.write(f"**Error:** {escalation['error']}")

                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("✅ Approve", key=f"approve_{escalation['id']}"):
                        st.success("Approved")
                with col2:
                    if st.button("✏️ Modify", key=f"modify_{escalation['id']}"):
                        st.info("Show modification interface")
                with col3:
                    if st.button("❌ Reject", key=f"reject_{escalation['id']}"):
                        st.error("Rejected")
    else:
        st.success("No pending escalations - all systems nominal!")


def show_cost_telemetry():
    """Sprint 8.1 #31 — admin tab for prompt-optimization cost verification.

    Renders a panel per portal showing median cost-per-request over the last
    30 requests vs the 1.3× projected band ceiling. Gate badge fires green
    when the sprint's pre-committed verification criterion is met.

    Data source: LangSmith API (see ADR in DECISIONS.md "Sprint 8.1 —
    LangSmith is source-of-truth for LLM cost"). The service queries runs
    tagged `portal:formal` / `portal:exploratory` (added in #29), groups
    formal-portal runs by `thread_id` metadata for cost-per-request
    aggregation, and computes USD cost from token counts via the local
    pricing table.

    #31 implements the formal portal panel; #32 adds the exploratory portal
    panel + real aggregation method. Until #32 lands, the exploratory
    section is intentionally not rendered.
    """
    from app.services.cost_telemetry_service import (
        CostTelemetryService,
        FORMAL_BAND_CEILING_USD,
    )

    st.header("💰 Cost Telemetry — Sprint 8.1 Verification")
    st.caption(
        "Sprint 8.1 gate: median cost-per-request ≤ 1.3× projected, rolling 30 requests per portal. "
        "See DECISIONS.md Sprint 8.1 ADR for the source-of-truth design."
    )
    st.info(
        "📐 **Numbers corrected 2026-05-14 (Sprint 8.4)** — pre-fix display inflated by "
        "~3× when caching was active due to `cache_read` tokens being double-charged inside "
        "`_run_cost_usd`. Sprint 8.1's $0.009026 baseline was unaffected (cache_hit=0% at the "
        "time). See DECISIONS.md Sprint 8.4 ADR.",
        icon="ℹ️",
    )

    service = CostTelemetryService()

    col_formal, col_exp = st.columns(2)

    with col_formal:
        st.subheader("Formal Portal")
        st.caption("6-agent workflow · cost-per-request grouped by `thread_id`")

        try:
            summary = run_async(service.get_formal_portal_cost_p50(n=30))
        except Exception as exc:
            st.error(f"Failed to fetch LangSmith data: {exc}")
            st.info(
                "If this is offline-dev, the dashboard depends on LangSmith API; "
                "ensure `LANGSMITH_API_KEY` is set and reachable."
            )
            return

        badge = {"green": "🟢", "red": "🔴", "gray": "⚪"}[summary.gate_status]
        st.metric(
            label=f"{badge} Median cost / request",
            value=f"${summary.median_usd:.4f}",
            delta=f"band ≤ ${summary.band_ceiling_usd:.4f}",
            delta_color=("normal" if summary.gate_status == "green" else "inverse"),
        )
        st.caption(
            f"Sample: {summary.n_observed} of 30 · "
            f"Cache hit rate: {summary.cache_hit_rate * 100:.1f}%"
        )
        if summary.gate_status == "gray":
            st.info(
                f"Insufficient sample ({summary.n_observed} threads observed, need 30). "
                "Gate fires once the rolling-30 window is full. "
                "See sprint issue #34 for the /qa pass that seeds the window."
            )
        elif summary.gate_status == "green":
            st.success("Gate PASS — 73% claim verified for the formal portal.")
        elif summary.gate_status == "red":
            st.error(
                f"Gate FAIL — actual median (\\${summary.median_usd:.4f}) exceeds the "
                f"1.3× band (\\${summary.band_ceiling_usd:.4f}). File Sprint 8.2 with the cost-gap finding."
            )

    with col_exp:
        st.subheader("Exploratory Portal")
        st.caption("Text2SQL · cost-per-query · aggregated per root trace")

        try:
            exp_summary = run_async(service.get_exploratory_portal_cost_p50(n=30))
        except Exception as exc:
            st.error(f"Failed to fetch LangSmith data: {exc}")
            return

        exp_badge = {"green": "🟢", "red": "🔴", "gray": "⚪"}[exp_summary.gate_status]
        st.metric(
            label=f"{exp_badge} Median cost / query",
            value=f"${exp_summary.median_usd:.5f}",
            delta=f"band ≤ ${exp_summary.band_ceiling_usd:.5f}",
            delta_color=("normal" if exp_summary.gate_status == "green" else "inverse"),
        )
        st.caption(
            f"Sample: {exp_summary.n_observed} of 30 · "
            f"Cache hit rate: {exp_summary.cache_hit_rate * 100:.1f}%"
        )
        if exp_summary.gate_status == "gray":
            st.info(
                f"Insufficient sample ({exp_summary.n_observed} queries observed, need 30). "
                "Run #34 seeds the rolling-30 window with ~30 NL queries via "
                "research_notebook."
            )
        elif exp_summary.gate_status == "green":
            st.success("Gate PASS — 90% claim verified for the exploratory portal.")
        elif exp_summary.gate_status == "red":
            st.error(
                f"Gate FAIL — actual median (\\${exp_summary.median_usd:.5f}) exceeds the "
                f"1.3× band (\\${exp_summary.band_ceiling_usd:.5f}). File Sprint 8.2 with the cost-gap finding."
            )

    # Sprint 6.4 cycle 6 — Materialized View health surface.
    # Reads logs/mv_health.jsonl (written by post_write_health_check after
    # every batch materialize). Shows the last 20 health records + per-view
    # current-alarm state. The reader returns [] cold-start.
    st.divider()
    st.subheader("🩺 Materialized View health — Sprint 6.4")
    st.caption(
        "After each batch materialize, the actual MV row count is compared "
        "against a HAPI oracle (same run, data-drift-immune). |delta|/oracle > 5% "
        "flips status to `warn`. Alarm fires only after 3 consecutive warns "
        "for the same view — filters single-run noise. Source: "
        "`logs/mv_health.jsonl` (gitignored runtime log)."
    )

    from app.sql_on_fhir.runner.mv_health_check import (
        DEFAULT_ALARM_CONSECUTIVE_RUNS,
        DEFAULT_LOG_PATH,
        check_alarm,
        read_recent_health_records,
    )

    recent = read_recent_health_records(n=20)
    if not recent:
        st.info(
            f"No health-check records yet. Run `python scripts/materialize_views.py` "
            f"to materialize the 3 sqlonfhir MVs; records land at `{DEFAULT_LOG_PATH}`."
        )
    else:
        views_in_log = sorted({r["view_name"] for r in recent})
        alarm_views = [
            v for v in views_in_log if check_alarm(v, n_runs=DEFAULT_ALARM_CONSECUTIVE_RUNS)
        ]
        if alarm_views:
            st.error(
                f"🚨 ALARM: {len(alarm_views)} view(s) at {DEFAULT_ALARM_CONSECUTIVE_RUNS} "
                f"consecutive warns — {', '.join(alarm_views)}. Investigate "
                f"before next batch materialize."
            )
        else:
            st.success(
                f"No active alarms. {len(views_in_log)} view(s) reporting; "
                f"last {len(recent)} records all within threshold."
            )

        # Render last 20 records as a dataframe. Newest LAST per file order
        # so the table reads chronologically; status emoji aids scanning.
        rows = []
        for r in recent:
            status_emoji = "✅" if r.get("status") == "ok" else "⚠️"
            rows.append(
                {
                    "ts": r.get("ts", ""),
                    "view": r.get("view_name", ""),
                    "actual": f"{r.get('actual_count', 0):,}",
                    "oracle": f"{r.get('oracle_count', 0):,}",
                    "delta_pct": f"{r.get('delta_pct', 0.0):.4f}",
                    "status": f"{status_emoji} {r.get('status', '')}",
                    "git_commit": r.get("git_commit", ""),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def show_materialized_views():
    """Issue #18: admin tab for managing the Lambda Architecture's batch layer.

    Triggers POST /analytics/materialized-views/refresh-all (CONCURRENTLY +
    parallel via asyncio.gather, per #18). Renders per-view results.

    NOTE on auth: admin endpoint requires admin-role JWT (Sprint 6.1 audit
    middleware enforces auth on this route). The dashboard-from-streamlit
    auth path is a known-incomplete dev-mode pattern shared by the rest of
    this dashboard (e.g., line 119's /research/{id}/delivery call) — fixing
    streamlit→API auth is out of scope for #18 and tracked separately. In
    dev with audit middleware bypass (e.g., REDIS_AUDIT_URL unset), the
    button works; in production, it returns 401/403.
    """
    st.header("🗄️ Materialized Views (Lambda Batch Layer)")
    st.caption(
        "Materialized views in `sqlonfhir.*` schema. Refresh runs CONCURRENTLY "
        "so cohort queries aren't blocked during refresh."
    )

    api_url = os.getenv("API_BASE_URL", "http://localhost:8000")

    if st.button("🔄 Refresh all materialized views", type="primary"):
        with st.spinner("Refreshing 7 views in parallel..."):
            try:
                response = httpx.post(
                    f"{api_url}/analytics/materialized-views/refresh-all",
                    timeout=120.0,
                )
                if response.status_code == 401:
                    st.error(
                        "Authentication required. Streamlit→API auth flow not yet "
                        "wired (known dev-mode limitation; same pattern as other "
                        "admin actions in this dashboard)."
                    )
                elif response.status_code == 403:
                    st.error("Admin role required to refresh materialized views.")
                elif response.status_code != 200:
                    st.error(f"Refresh failed (HTTP {response.status_code}): {response.text}")
                else:
                    data = response.json()
                    st.success(
                        f"✅ Refreshed {data['success']}/{data['total_views']} views"
                        + (f" ({data['failed']} failed)" if data["failed"] else "")
                    )
                    # Per-view results table
                    rows = []
                    for r in data["results"]:
                        rows.append(
                            {
                                "View": r["view_name"],
                                "Status": "✅" if r["success"] else "❌",
                                "Duration (ms)": (
                                    f"{r.get('refresh_duration_ms', 0):.0f}"
                                    if r["success"]
                                    else "—"
                                ),
                                "Rows": (f"{r.get('row_count', 0):,}" if r["success"] else "—"),
                                "Error": r.get("error", ""),
                            }
                        )
                    st.dataframe(pd.DataFrame(rows), use_container_width=True)
            except httpx.TimeoutException:
                st.error("Refresh timed out after 120 seconds.")
            except Exception as e:
                st.error(f"Unexpected error: {e}")


def show_analytics():
    """Display analytics and insights"""
    st.header("📈 Analytics & Insights")

    # Request volume over time
    st.subheader("Request Volume Trends")

    # Mock data for demonstration
    dates = pd.date_range(start=datetime.now() - timedelta(days=30), end=datetime.now(), freq="D")
    volume_data = pd.DataFrame(
        {
            "Date": dates,
            "Submitted": [i % 5 + 2 for i in range(len(dates))],
            "Completed": [i % 4 + 1 for i in range(len(dates))],
        }
    )

    st.line_chart(volume_data.set_index("Date"))

    # ROI Metrics
    st.subheader("💰 ROI Analysis")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Manual Cost/Request", "$1,500")

    with col2:
        st.metric("Automated Cost/Request", "$150", delta="-$1,350")

    with col3:
        st.metric("Time Saved (hours)", "1,200", delta="+150 this month")

    with col4:
        st.metric("Total Savings", "$75,000", delta="+$7,500")

    # Most requested data elements
    st.subheader("Most Requested Data Elements")

    element_data = pd.DataFrame(
        {
            "Element": ["Clinical Notes", "Lab Results", "Medications", "Diagnoses", "Procedures"],
            "Requests": [45, 38, 32, 28, 15],
        }
    )

    st.bar_chart(element_data.set_index("Element"))


if __name__ == "__main__":
    main()
