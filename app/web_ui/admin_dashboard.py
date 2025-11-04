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
from dotenv import load_dotenv
from sqlalchemy import select

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.orchestrator import ResearchRequestOrchestrator
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade
from app.agents import (
    RequirementsAgent,
    PhenotypeValidationAgent,
    CalendarAgent,
    DataExtractionAgent,
    QualityAssuranceAgent,
    DeliveryAgent,
)
from app.database import get_db_session, get_engine
from app.database.models import AgentExecution
from app.services.approval_service import ApprovalService


def run_async(coroutine):
    """
    Run async code in Streamlit's persistent event loop.

    Uses the loop set up at module import time to ensure all
    database operations use the same loop.
    """
    return _streamlit_loop.run_until_complete(coroutine)


def get_status_badge(state: str) -> str:
    """Get colored status badge for request state"""
    state_colors = {
        "delivered": "🟢",
        "complete": "🟢",
        "data_delivery": "🟡",
        "qa_validation": "🟡",
        "data_extraction": "🟡",
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

        # ====================================================================
        # LangGraph Migration Feature Flag (Sprint 6.5 + 6.6)
        # ====================================================================
        # Check if LangGraph workflow is enabled via environment variable
        use_langgraph = os.getenv("USE_LANGGRAPH_WORKFLOW", "false").lower() == "true"

        if use_langgraph:
            # Use new LangGraph declarative orchestrator
            st.caption("🆕 Using LangGraph Orchestrator (Beta)")
            orchestrator = LangGraphRequestFacade(
                use_real_agents=True,  # Use production agents
                use_persistence=True,  # Enable checkpointing
            )
        else:
            # Use legacy custom orchestrator (default)
            orchestrator = ResearchRequestOrchestrator()

            # Get HAPI FHIR database URL from environment
            hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")

            # Register all agents (phenotype agent needs HAPI database for ViewDefinitions)
            orchestrator.register_agent("requirements_agent", RequirementsAgent())
            orchestrator.register_agent(
                "phenotype_agent", PhenotypeValidationAgent(database_url=hapi_db_url)
            )
            orchestrator.register_agent("calendar_agent", CalendarAgent())
            orchestrator.register_agent("extraction_agent", DataExtractionAgent())
            orchestrator.register_agent("qa_agent", QualityAssuranceAgent())
            orchestrator.register_agent("delivery_agent", DeliveryAgent())

        st.session_state.orchestrator = orchestrator


def show_requests_sidebar():
    """Show all submitted requests in sidebar"""
    st.header("📋 All Requests")

    # Get all requests
    requests = run_async(st.session_state.orchestrator.get_all_active_requests())

    # Search box
    search_term = st.text_input(
        "🔍 Search", key="search_requests", placeholder="Search by ID or researcher"
    )

    # Status filter
    all_statuses = [
        "delivered",
        "complete",
        "in_progress",
        "data_extraction",
        "qa_validation",
        "failed",
        "not_feasible",
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
            if search_term.lower() in r.get("id", "").lower()
            or search_term.lower() in r.get("researcher_name", "").lower()
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
        for req in filtered_requests:
            badge = get_status_badge(req.get("current_state", ""))
            req_id = req.get("id", "Unknown")
            req_short = req_id[:12] + "..." if len(req_id) > 12 else req_id

            with st.expander(f"{badge} {req_short}"):
                st.write(f"**Researcher:** {req.get('researcher_name', 'N/A')}")
                st.write(f"**Status:** {req.get('current_state', 'N/A').replace('_', ' ').title()}")

                created_at = req.get("created_at", "")
                if created_at:
                    st.write(
                        f"**Started:** {created_at[:19] if isinstance(created_at, str) else created_at}"
                    )

                # Check delivery
                delivery = check_delivery_status(req_id)
                if delivery.get("delivered"):
                    st.write(f"**Cohort:** {delivery.get('cohort_size', 0):,} patients")
                    st.write(f"**Files:** {len(delivery.get('files', []))} ready")

                if st.button("View Details", key=f"view_{req_id}"):
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
        st.metric("Current Agent", status.get("current_agent", "None").replace("_", " ").title())
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

    # Download Section
    show_download_section(request_id)

    # Close button
    if st.button("Close", type="secondary", use_container_width=True):
        del st.session_state.selected_request
        st.rerun()


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
        tab1, tab2, tab3, tab4, tab5 = st.tabs(
            [
                "📊 Overview",
                "🤖 Agent Metrics",
                "✋ Pending Approvals",
                "🚨 Escalations",
                "📈 Analytics",
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

    # Auto-refresh logic
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()


def show_overview():
    """Display system overview"""
    st.header("System Overview")

    # Get all active requests
    requests = run_async(st.session_state.orchestrator.get_all_active_requests())

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
            # Get all registered agents from orchestrator (shows ALL agents, not just executed ones)
            registered_agents = list(st.session_state.orchestrator.agents.keys())

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

    all_metrics = run_async(fetch_agent_metrics())

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

        approvals_db = run_async(fetch_approvals())

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
        "extraction": "📊",
        "qa": "✓",
        "scope_change": "🔄",
    }

    type_label_map = {
        "requirements": "Requirements Review",
        "phenotype_sql": "SQL REVIEW (CRITICAL)",
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
                if not reviewer_email:
                    st.error("Please enter your email address")
                else:
                    handle_approval_response(approval_id, "approve", reviewer_email, "", {})

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
                if not reviewer_email:
                    st.error("Please enter your email address")
                else:
                    handle_approval_response(
                        approval_id, "modify", reviewer_email, notes, modifications
                    )
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
                if not reviewer_email:
                    st.error("Please enter your email address")
                elif not reject_reason:
                    st.error("Please provide a reason for rejection")
                else:
                    handle_approval_response(
                        approval_id, "reject", reviewer_email, reject_reason, {}
                    )
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
    sql_query = data.get("sql_query", "N/A")
    st.code(sql_query, language="sql")

    # Metrics
    col1, col2, col3 = st.columns(3)

    with col1:
        cohort = data.get("estimated_cohort", "Unknown")
        st.metric("Estimated Cohort", cohort)

    with col2:
        feasibility = data.get("feasibility_score", 0)
        st.metric("Feasibility Score", f"{feasibility:.2f}")

    with col3:
        availability = data.get("data_availability", {}).get("overall_availability", 0)
        st.metric("Data Availability", f"{availability:.1%}")

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
    """Handle approval response (approve/reject/modify) using direct database access"""
    try:

        async def process_approval():
            async with get_db_session() as session:
                approval_service = ApprovalService(session)

                if decision == "approve":
                    await approval_service.approve(approval_id, reviewer, notes, modifications)
                elif decision == "reject":
                    await approval_service.reject(approval_id, reviewer, notes or "Rejected")
                elif decision == "modify":
                    await approval_service.modify(approval_id, reviewer, modifications, notes)
                else:
                    raise ValueError(f"Invalid decision: {decision}")

        run_async(process_approval())

        if decision == "approve":
            st.success(f"✅ Approval {approval_id} approved! Workflow will continue automatically.")
        elif decision == "reject":
            st.error(
                f"❌ Approval {approval_id} rejected. Request will return to originating agent."
            )
        elif decision == "modify":
            st.success(
                f"✏️ Approval {approval_id} approved with modifications. Workflow will continue with your changes."
            )

        # Trigger refresh after 2 seconds
        time.sleep(2)
        st.rerun()

    except Exception as e:
        st.error(f"Error processing approval: {str(e)}")
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
