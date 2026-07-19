"""
ResearchFlow Researcher Portal

Streamlit interface for researchers to submit and track data requests.
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
import httpx
from datetime import datetime, timedelta
from dotenv import load_dotenv
import extra_streamlit_components as stx

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
from app.database import get_engine


def run_async(coroutine):
    """
    Run async code in Streamlit's persistent event loop.

    Uses the loop set up at module import time to ensure all
    database operations use the same loop.
    """
    return _streamlit_loop.run_until_complete(coroutine)


# Cookie manager singleton
_cookie_manager = None


def get_cookie_manager():
    """Get or create cookie manager instance"""
    global _cookie_manager
    if _cookie_manager is None:
        _cookie_manager = stx.CookieManager()
    return _cookie_manager


def load_researcher_email() -> str:
    """Load researcher email from cookie"""
    try:
        cookie_manager = get_cookie_manager()
        return cookie_manager.get("researcher_email") or ""
    except Exception as e:
        st.warning(f"Could not load saved email: {str(e)}")
        return ""


def save_researcher_email(email: str):
    """Save researcher email to cookie (30 days)"""
    try:
        cookie_manager = get_cookie_manager()
        cookie_manager.set(
            "researcher_email", email, expires_at=datetime.now() + timedelta(days=30)
        )
    except Exception as e:
        st.warning(f"Could not save email: {str(e)}")


def clear_researcher_email():
    """Clear saved researcher email"""
    try:
        cookie_manager = get_cookie_manager()
        cookie_manager.delete("researcher_email")
    except Exception as e:
        st.warning(f"Could not clear saved email: {str(e)}")


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
        # Query database directly (FIXED: no longer depends on API server running)
        from app.database.models import DataDelivery
        from sqlalchemy import select
        from app.database import get_db_session
        import json

        async def get_delivery():
            async with get_db_session() as session:
                result = await session.execute(
                    select(DataDelivery).where(DataDelivery.request_id == request_id)
                )
                return result.scalar_one_or_none()

        delivery = run_async(get_delivery())

        if not delivery:
            return {"delivered": False, "files": []}

        # Build response from database record
        # Get file list from database (populated by delivery_agent)
        file_list = delivery.file_list or []

        # Convert filenames to file info dicts with size information
        files = []

        # Use FileStorageService to get correct path (handles env-specific paths)
        from app.services.file_storage import FileStorageService

        file_storage = FileStorageService()
        request_dir = file_storage._get_request_directory(request_id)

        for filename in file_list:
            try:
                # Calculate file size from actual file
                file_path = request_dir / filename

                if file_path.exists():
                    size_bytes = file_path.stat().st_size
                    size_mb = size_bytes / (1024 * 1024)
                else:
                    size_mb = 0.0

                files.append({"filename": filename, "size_mb": size_mb})
            except Exception as e:
                # Fallback if size calculation fails
                files.append({"filename": filename, "size_mb": 0.0})

        return {
            "delivered": True,
            "files": files,
            "cohort_size": delivery.cohort_size or 0,
            "delivery_location": str(request_dir),
            "delivery_metadata": delivery.delivery_metadata or {},
            "data_elements": delivery.data_elements or [],
        }
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


def show_preview_data_section_researcher(request_id: str, status: dict):
    """Show preview extraction status (not actual data - informatician only)"""
    from app.database.models import DataDelivery
    from sqlalchemy import select
    from app.database import get_db_session

    st.markdown("### 🔍 Preview Extraction Status")

    try:

        async def get_preview_data():
            async with get_db_session() as session:
                result = await session.execute(
                    select(DataDelivery).where(DataDelivery.request_id == request_id)
                )
                return result.scalar_one_or_none()

        delivery = run_async(get_preview_data())

        if delivery and delivery.preview_data:
            st.success("✅ Preview extraction complete!")
            st.caption(
                "Your data team has extracted a sample preview and is reviewing it before proceeding to full data extraction."
            )

            # Show preview QA status (no actual data)
            if delivery.preview_qa_report:
                qa_report = delivery.preview_qa_report
                status_icon = "✅" if qa_report.get("overall_status") == "passed" else "❌"
                st.info(
                    f"{status_icon} Preview QA Status: {qa_report.get('overall_status', 'unknown').upper()}"
                )
                st.caption(
                    "The informatician is reviewing the preview before authorizing full data extraction."
                )

        elif status.get("current_state") in ["preview_extraction", "preview_qa"]:
            st.info(
                "⏳ Preview data is being extracted and validated. Please check back shortly..."
            )
        elif status.get("current_state") in [
            "data_extraction",
            "qa_validation",
            "delivery_review",
            "data_delivery",
            "delivered",
            "complete",
        ]:
            st.success("✅ Preview was reviewed and approved by informatician")
            st.caption("Full data extraction is in progress")
        else:
            st.caption("Preview extraction will begin after SQL approval")

    except Exception as e:
        st.caption("Preview extraction status not available yet")


@st.dialog("Request Details", width="large")
def show_request_details_modal(request_id: str):
    """Show request details in a modal dialog"""

    status = run_async(st.session_state.orchestrator.get_request_status(request_id))

    if not status:
        st.error(f"Request not found: {request_id}")
        return

    # Header
    st.subheader(f"Request: {request_id}")

    # Metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        badge = get_status_badge(status["current_state"])
        st.metric("Status", f"{badge} {status['current_state'].replace('_', ' ').title()}")
    with col2:
        st.metric(
            "Current Agent", (status.get("current_agent") or "None").replace("_", " ").title()
        )
    with col3:
        try:
            started = datetime.fromisoformat(status["started_at"])
            duration = datetime.now() - started
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
        for activity in reversed(status["agents_involved"][-10:]):  # Last 10 activities
            agent = activity.get("agent", "").replace("_", " ").title()
            task = activity.get("task", "").replace("_", " ").title()
            timestamp = activity.get("timestamp", "")[:19] if activity.get("timestamp") else "N/A"
            st.markdown(f"**{timestamp}** - {agent}: {task}")
    else:
        st.info("No agent activity yet")

    st.markdown("---")

    # Preview Data Section (NEW - Sprint X)
    show_preview_data_section_researcher(request_id, status)

    st.markdown("---")

    # Data Delivery Status
    st.markdown("### 📦 Data Delivery")
    delivery_info = check_delivery_status(request_id)

    # FIXED: Only show "ready" if files actually exist
    if delivery_info.get("delivered") and len(delivery_info.get("files", [])) > 0:
        st.success("✅ Data ready for download!")

        # Metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Cohort Size", f"{delivery_info.get('cohort_size', 0):,}")
        with col2:
            st.metric("Data Elements", len(delivery_info.get("data_elements", [])))
        with col3:
            st.metric("Files", len(delivery_info.get("files", [])))

        st.info("💡 Go to the 'Request Details' tab to download your data files")

        st.markdown("---")
    elif delivery_info.get("delivered") and len(delivery_info.get("files", [])) == 0:
        # Delivery record exists but no files (workflow bug - delivery_agent didn't execute properly)
        st.warning("⚠️ Delivery initiated but files not yet available")
        st.caption(
            "The delivery process may have encountered an issue. Please contact support if this persists."
        )
        st.markdown("---")

        # Optional Meeting Button (NEW - Sprint X)
        st.markdown("### 📅 Schedule Kickoff Meeting (Optional)")
        st.caption("Schedule a meeting with the data team to discuss your dataset")

        if st.button(
            "📅 Schedule Meeting",
            type="secondary",
            use_container_width=True,
            key=f"schedule_meeting_{request_id}",
        ):
            # ⚠️ DISABLED: trigger_agent_task() not supported with LangGraph
            # This feature requires custom orchestrator or implementation as workflow state
            st.warning(
                "⚠️ Meeting scheduling is not available when using LangGraph workflow. "
                "Please contact the data team directly to schedule a meeting."
            )
            st.info("📧 Email: data-team@hospital.org")

            # TODO: Implement meeting scheduling as part of LangGraph workflow
            # Option 1: Add as workflow state after delivery
            # Option 2: Use separate API endpoint for post-delivery meetings
            # Option 3: Manually schedule via email/calendar

            # OLD CODE (commented out - doesn't work with LangGraphRequestFacade):
            # try:
            #     meeting_scheduled = run_async(
            #         st.session_state.orchestrator.trigger_agent_task(
            #             request_id=request_id,
            #             agent_id="calendar_agent",
            #             task="schedule_kickoff_meeting",
            #             context={"meeting_type": "post_delivery_kickoff"},
            #         )
            #     )
            #
            #     if meeting_scheduled.get("meeting_scheduled"):
            #         st.success(f"✅ Meeting scheduled! Check your email for details.")
            #     else:
            #         st.info("📧 Meeting request sent. You'll receive a calendar invite shortly.")
            # except Exception as e:
            #     st.warning(f"Could not schedule meeting: {str(e)}")
            #     st.info("Please contact the data team directly to schedule a meeting.")
    else:
        current_state = status["current_state"]
        st.info(
            f"Data not yet delivered. Current status: {current_state.replace('_', ' ').title()}"
        )

    # Close button
    if st.button("Close", type="secondary", use_container_width=True):
        del st.session_state.modal_request
        st.rerun()


def initialize_orchestrator():
    """Initialize LangGraph orchestrator.

    Sprint 7.2 Phase 4: A2A's ResearchRequestOrchestrator deleted; the
    USE_LANGGRAPH_WORKFLOW + LANGGRAPH_ROLLOUT_PCT feature flags are
    retired with it. LangGraph is now the unconditional default.
    """
    if "orchestrator" not in st.session_state:
        # Ensure database engine is initialized for current event loop
        # This prevents "Queue is bound to a different event loop" errors
        get_engine()

        orchestrator = LangGraphRequestFacade(
            use_real_agents=True,  # Use production agents
            use_persistence=True,  # Enable checkpointing
        )
        st.session_state.orchestrator = orchestrator


def main():
    """Main researcher portal application"""
    st.set_page_config(
        page_title="ResearchFlow - Data Request Portal", page_icon="🔬", layout="wide"
    )

    # Initialize orchestrator
    initialize_orchestrator()

    # Header
    st.title("🔬 ResearchFlow - Clinical Data Request Platform")
    st.caption("AI-powered research data requests | From request to data in hours")

    # Sidebar - My Requests
    with st.sidebar:
        st.header("📊 My Requests")

        # Initialize session state
        if "user_requests" not in st.session_state:
            st.session_state.user_requests = []  # Track just-submitted requests
        if "researcher_email_input" not in st.session_state:
            st.session_state.researcher_email_input = load_researcher_email()

        # Researcher identification
        st.subheader("👤 Your Identity")
        researcher_email = st.text_input(
            "Your Email",
            value=st.session_state.researcher_email_input,
            placeholder="researcher@hospital.edu",
            key="sidebar_email",
            help="Enter your email to view your requests",
        )

        col1, col2 = st.columns([2, 1])
        with col1:
            remember_me = st.checkbox(
                "Remember me", value=bool(st.session_state.researcher_email_input)
            )
        with col2:
            if st.button("Clear", help="Clear saved email"):
                clear_researcher_email()
                st.session_state.researcher_email_input = ""
                st.rerun()

        # Save email to cookie if Remember Me is checked
        if (
            remember_me
            and researcher_email
            and researcher_email != st.session_state.researcher_email_input
        ):
            save_researcher_email(researcher_email)
            st.session_state.researcher_email_input = researcher_email

        st.markdown("---")

        # Fetch requests from database if email provided
        if researcher_email:
            try:
                # Query database for all researcher's requests
                db_requests = run_async(
                    st.session_state.orchestrator.get_requests_by_researcher(researcher_email)
                )

                # Track just-submitted requests for "new" badge
                just_submitted_ids = set(st.session_state.user_requests)

                if db_requests:
                    st.caption(f"Found {len(db_requests)} request(s)")

                    for status in db_requests:
                        req_id = status["request_id"]

                        # Get status badge
                        badge = get_status_badge(status["current_state"])

                        # Add "just submitted" indicator
                        is_new = req_id in just_submitted_ids
                        new_indicator = " 🆕" if is_new else ""

                        request_label = f"{badge} Request #{req_id[:8]}...{new_indicator}"

                        with st.expander(request_label):
                            # Status with badge
                            st.write(
                                f"**Status:** {status['current_state'].replace('_', ' ').title()}"
                            )
                            st.write(f"**Started:** {status['started_at'][:19]}")

                            # Show cohort size if delivered
                            delivery_info = check_delivery_status(req_id)
                            if delivery_info.get("delivered"):
                                st.write(
                                    f"**Cohort Size:** {delivery_info.get('cohort_size', 'N/A')} patients"
                                )
                                st.write(
                                    f"**Files:** {len(delivery_info.get('files', []))} files ready"
                                )

                            if st.button("View Details", key=f"view_{req_id}"):
                                st.session_state.modal_request = req_id
                                # Issue #35: also select this request so the
                                # "📋 Request Details" tab (and its download UI)
                                # resolves for a returning researcher who never
                                # submitted in this browser session. Previously
                                # only new-request submission set selected_request,
                                # so the modal's "go to Request Details tab" hint
                                # was a dead pointer after a page refresh.
                                st.session_state.selected_request = req_id
                                # Remove from "just submitted" set after viewing
                                if req_id in just_submitted_ids:
                                    st.session_state.user_requests.remove(req_id)

                    # Show modal if a request was clicked
                    if st.session_state.get("modal_request"):
                        show_request_details_modal(st.session_state.modal_request)
                else:
                    st.info("No requests yet. Submit a new request below!")

            except Exception as e:
                st.error(f"Error loading requests: {str(e)}")
        else:
            st.info("👆 Enter your email to view your requests")

    # Main content area
    tab1, tab2 = st.tabs(["🆕 New Request", "📋 Request Details"])

    with tab1:
        show_new_request_form()

    with tab2:
        show_request_details()


def show_new_request_form():
    """Display new request submission form"""
    st.header("Submit New Data Request")

    st.markdown(
        """
    Describe your research data needs in natural language. Our AI assistant will help you
    define your requirements through a conversational interface.
    """
    )

    # Researcher information
    with st.form("researcher_info"):
        st.subheader("👤 Researcher Information")

        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Name *", placeholder="Dr. Jane Smith")
            department = st.text_input("Department", placeholder="Cardiology")

        with col2:
            email = st.text_input("Email *", placeholder="jsmith@hospital.edu")
            irb_number = st.text_input("IRB Number *", placeholder="IRB-2024-001")

        # Data request
        st.subheader("📝 Data Request")
        request_text = st.text_area(
            "Describe your data needs *",
            placeholder="Example: I need clinical notes and lab results for heart failure patients admitted in 2024 who had a prior diabetes diagnosis.",
            height=100,
        )

        # Inclusion/Exclusion Criteria
        st.subheader("🎯 Study Criteria")

        col1, col2 = st.columns(2)
        with col1:
            inclusion_criteria = st.text_area(
                "Inclusion Criteria",
                placeholder="Example:\n- Age >= 18 years\n- Diagnosed with diabetes\n- Admitted in 2024",
                height=100,
                help="Enter criteria for patient inclusion (one per line)",
            )

        with col2:
            exclusion_criteria = st.text_area(
                "Exclusion Criteria",
                placeholder="Example:\n- Pregnant patients\n- Age < 18 years",
                height=100,
                help="Enter criteria for patient exclusion (one per line)",
            )

        # Time Period
        st.subheader("📅 Time Period")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "Start Date", value=None, help="Start date for data collection period"
            )
        with col2:
            end_date = st.date_input(
                "End Date", value=None, help="End date for data collection period"
            )

        # Data Elements
        st.subheader("📊 Data Elements")
        data_elements = st.multiselect(
            "Select data elements needed",
            options=[
                "Demographics (age, gender, race)",
                "Diagnoses (ICD codes)",
                "Procedures (CPT/HCPCS codes)",
                "Medications (prescriptions)",
                "Lab Results (LOINC codes)",
                "Vital Signs (BP, HR, temperature)",
                "Clinical Notes",
                "Imaging Reports",
                "Encounter Data (visits, admissions)",
            ],
            default=["Demographics (age, gender, race)"],
            help="Select all data types you need for your study",
        )

        # PHI Level
        st.subheader("🔒 Data Privacy Level")
        phi_level = st.selectbox(
            "PHI/De-identification Level *",
            options=[
                "De-identified (HIPAA Safe Harbor)",
                "Limited Dataset (dates allowed)",
                "Identified (full PHI)",
            ],
            index=0,
            help="Select the level of patient identifiers needed for your study",
        )

        submit = st.form_submit_button("Submit Request", type="primary")

        if submit:
            if not all([name, email, irb_number, request_text]):
                st.error("Please fill in all required fields (*)")
            else:
                # Submit request
                with st.spinner("Processing your request (may take 30-60 seconds)..."):
                    try:
                        # Map PHI level selection to internal format
                        phi_level_map = {
                            "De-identified (HIPAA Safe Harbor)": "de-identified",
                            "Limited Dataset (dates allowed)": "limited_dataset",
                            "Identified (full PHI)": "identified",
                        }

                        # Parse inclusion/exclusion criteria (split by newlines, filter empty)
                        inclusion_list = (
                            [c.strip() for c in inclusion_criteria.split("\n") if c.strip()]
                            if inclusion_criteria
                            else []
                        )
                        exclusion_list = (
                            [c.strip() for c in exclusion_criteria.split("\n") if c.strip()]
                            if exclusion_criteria
                            else []
                        )

                        # Build structured requirements (will be passed to Requirements Agent)
                        structured_requirements = {
                            "inclusion_criteria": inclusion_list,
                            "exclusion_criteria": exclusion_list,
                            "data_elements": data_elements if data_elements else ["demographics"],
                            "time_period": {
                                "start": start_date.isoformat() if start_date else None,
                                "end": end_date.isoformat() if end_date else None,
                            },
                            "phi_level": phi_level_map.get(phi_level, "de-identified"),
                        }

                        researcher_info = {
                            "name": name,
                            "email": email,
                            "department": department,
                            "irb_number": irb_number,
                            "structured_requirements": structured_requirements,  # Pass form data
                        }

                        # Create async event loop to submit request with timeout protection
                        # from_formal_portal=True enables form-based validation (skip conversational mode)
                        try:
                            request_id = run_async(
                                asyncio.wait_for(
                                    st.session_state.orchestrator.process_new_request(
                                        researcher_request=request_text,
                                        researcher_info=researcher_info,
                                        from_formal_portal=True,  # NEW: Enable form-based validation
                                    ),
                                    timeout=120.0,  # 2 minute timeout
                                )
                            )
                        except asyncio.TimeoutError:
                            st.error(
                                "❌ Request processing timed out after 2 minutes. Please try again or contact support if the issue persists."
                            )
                            return

                        # Add to session state
                        if "user_requests" not in st.session_state:
                            st.session_state.user_requests = []
                        st.session_state.user_requests.append(request_id)

                        st.success(f"✅ Request submitted! Request ID: {request_id}")
                        st.balloons()

                        # Switch to details tab
                        st.session_state.selected_request = request_id

                    except Exception as e:
                        st.error(f"Failed to submit request: {str(e)}")


def show_request_details():
    """Display detailed information about a request"""
    if "selected_request" not in st.session_state:
        st.info("Select a request from the sidebar to view details")
        return

    request_id = st.session_state.selected_request
    status = run_async(st.session_state.orchestrator.get_request_status(request_id))

    if not status:
        st.error(f"Request not found: {request_id}")
        return

    # Request header
    st.header(f"Request: {request_id}")

    # Status overview
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Status", status["current_state"])
    with col2:
        st.metric("Current Agent", status.get("current_agent", "None"))
    with col3:
        started = datetime.fromisoformat(status["started_at"])
        duration = datetime.now() - started
        st.metric("Duration", f"{duration.seconds // 60} min")

    # Workflow progress
    st.subheader("🔄 Workflow Progress")

    workflow_states = [
        "new_request",
        "requirements_gathering",
        "feasibility_validation",
        "schedule_kickoff",
        "data_extraction",
        "qa_validation",
        "data_delivery",
        "delivered",
    ]

    current_idx = -1
    if status["current_state"] in workflow_states:
        current_idx = workflow_states.index(status["current_state"])

    progress = (current_idx + 1) / len(workflow_states) if current_idx >= 0 else 0
    st.progress(progress)

    # State history
    st.subheader("📊 Agent Activity")

    if status.get("agents_involved"):
        for activity in reversed(status["agents_involved"]):
            agent_name = activity["agent"].replace("_", " ").title()
            task_name = activity["task"].replace("_", " ").title()
            timestamp = activity["timestamp"][:19]

            st.markdown(f"**{timestamp}** - {agent_name}: {task_name}")
    else:
        st.info("No agent activity yet")

    # Researcher info
    st.subheader("👤 Researcher Information")
    researcher = status.get("researcher_info", {})
    st.write(f"**Name:** {researcher.get('name', 'N/A')}")
    st.write(f"**Email:** {researcher.get('email', 'N/A')}")
    st.write(f"**IRB:** {researcher.get('irb_number', 'N/A')}")

    # Data Delivery Section
    st.subheader("📦 Data Delivery")

    delivery_info = check_delivery_status(request_id)

    if delivery_info.get("delivered"):
        st.success("✅ Your data is ready for download!")

        # Delivery metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Cohort Size", f"{delivery_info.get('cohort_size', 0):,}")
        with col2:
            st.metric("Data Elements", len(delivery_info.get("data_elements", [])))
        with col3:
            st.metric("Files Available", len(delivery_info.get("files", [])))

        st.markdown("---")

        # Download options
        st.markdown("### 📥 Download Options")

        # Option 1: Download all as ZIP
        st.markdown("**Option 1: Download Complete Package (ZIP)**")
        st.caption("Includes all data files, data dictionary, QA report, and documentation")

        if st.button(
            "📦 Download Complete Package (ZIP)", type="primary", use_container_width=True
        ):
            with st.spinner("Preparing download..."):
                file_content, filename = download_file(request_id)
                if file_content:
                    st.download_button(
                        label="💾 Click here to save ZIP file",
                        data=file_content,
                        file_name=filename,
                        mime="application/zip",
                        type="primary",
                        use_container_width=True,
                    )
                    st.success(f"✅ Ready to download: {filename}")

        st.markdown("---")

        # Option 2: Download individual files
        st.markdown("**Option 2: Download Individual Files**")

        files = delivery_info.get("files", [])
        if files:
            for file_info in files:
                filename = file_info.get("filename", "unknown.csv")
                file_size = file_info.get("size_mb", 0)

                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"📄 **{filename}** ({file_size:.2f} MB)")
                with col2:
                    if st.button("Download", key=f"dl_{filename}", use_container_width=True):
                        with st.spinner(f"Downloading {filename}..."):
                            file_content, _ = download_file(request_id, filename)
                            if file_content:
                                st.download_button(
                                    label=f"💾 Save {filename}",
                                    data=file_content,
                                    file_name=filename,
                                    mime="text/csv" if filename.endswith(".csv") else "text/plain",
                                    key=f"save_{filename}",
                                    use_container_width=True,
                                )
        else:
            st.info("No files available for download")

        # QA Summary
        if delivery_info.get("qa_report_summary"):
            st.markdown("---")
            st.markdown("### ✅ Quality Assurance Summary")
            qa_summary = delivery_info["qa_report_summary"]
            st.json(qa_summary)

    else:
        # Not yet delivered
        current_state = status["current_state"]
        if current_state in ["delivered", "complete"]:
            st.warning("⏳ Data delivery is being prepared. Please check back in a few moments.")
        elif current_state in ["data_extraction", "qa_validation", "data_delivery"]:
            st.info(
                f"🔄 Your request is being processed. Current stage: {current_state.replace('_', ' ').title()}"
            )
            st.caption("You'll be able to download your data once processing is complete.")
        elif current_state == "failed":
            st.error("❌ Request failed. Please contact support for assistance.")
        elif current_state == "not_feasible":
            st.warning(
                "⚠️ Request was determined to be not feasible. Please review the feedback and submit a new request."
            )
        else:
            st.info(f"📋 Request is in progress: {current_state.replace('_', ' ').title()}")
            st.caption(
                "Data download will be available once the request is completed and delivered."
            )


if __name__ == "__main__":
    main()
