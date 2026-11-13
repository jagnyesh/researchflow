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
import html
import logging

import streamlit as st


logger = logging.getLogger(__name__)
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
from app.schemas._errors import log_internal_error

assert_encryption_key_present_if_production()

from app.langchain_orchestrator.request_facade import LangGraphRequestFacade
from app.agents.extraction_agent import FORM_DATA_ELEMENTS
from app.database import get_engine
from app.database.workflow_states import STATE_INFO, StateKind, WorkflowState


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
        ref = log_internal_error(logger, "Could not load saved email", e)
        st.warning(f"Could not load saved email (ref: {ref})")
        return ""


def save_researcher_email(email: str):
    """Save researcher email to cookie (30 days)"""
    try:
        cookie_manager = get_cookie_manager()
        cookie_manager.set(
            "researcher_email", email, expires_at=datetime.now() + timedelta(days=30)
        )
    except Exception as e:
        ref = log_internal_error(logger, "Could not save email", e)
        st.warning(f"Could not save email (ref: {ref})")


def clear_researcher_email():
    """Clear saved researcher email"""
    try:
        cookie_manager = get_cookie_manager()
        cookie_manager.delete("researcher_email")
    except Exception as e:
        ref = log_internal_error(logger, "Could not clear saved email", e)
        st.warning(f"Could not clear saved email (ref: {ref})")


def _state_info(value):
    """Registry entry for a stored state string, or None for a value that is not a member."""
    try:
        return WorkflowState(value).info
    except ValueError:
        return None


# The ledger lists every state a running request passes through, in the registry's
# lifecycle order, and ends at the state a successful run ends in (#436).
WORKFLOW_STATES = [
    state.value
    for state, info in STATE_INFO.items()
    if info.kind in (StateKind.IN_PROGRESS, StateKind.AWAITING_REVIEW)
] + [WorkflowState.COMPLETE.value]

# Same state categories the colored-circle emoji used to carry (#363).
_STATE_ICONS = {
    "delivered": ":material/check_circle:",
    "complete": ":material/check_circle:",
    "data_delivery": ":material/autorenew:",
    "qa_validation": ":material/autorenew:",
    "data_extraction": ":material/autorenew:",
    "delivery_review": ":material/pending_actions:",
    "preview_qa": ":material/hourglass_empty:",
    "preview_extraction": ":material/hourglass_empty:",
    "feasibility_validation": ":material/hourglass_empty:",
    "requirements_gathering": ":material/hourglass_empty:",
    "failed": ":material/error:",
    "not_feasible": ":material/error:",
}


def get_status_badge(state: str) -> str:
    """Material Symbol marking the request state's category"""
    return _STATE_ICONS.get(state.lower(), ":material/radio_button_unchecked:")


def _label(value) -> str:
    """snake_case identifier -> sentence-case label ('qa_validation' -> 'QA validation')"""
    words = str(value or "").split("_")
    words = [w.upper() if w.lower() in ("qa", "sql", "irb", "phi") else w for w in words]
    text = " ".join(w for w in words if w)
    return text[:1].upper() + text[1:]


def _agent_label(agent) -> str:
    return _label(agent) if agent else "Idle"


def _ts(value) -> str:
    return str(value or "")[:19].replace("T", " ")


_CSS = """
<style>
    :root {
        --rf-ink: #14181f;
        --rf-ink-2: #4a515c;
        --rf-ink-3: #6b727d;
        --rf-line: rgba(20, 24, 31, 0.08);
        --rf-raised: #f6f7f8;
        --rf-accent: #0b4fa8;
        --rf-mono: "Source Code Pro", ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    [data-testid="stMainBlockContainer"] h1 {
        font-size: 32px;
        font-weight: 500;
        letter-spacing: -0.01em;
        color: var(--rf-ink);
        padding-bottom: 4px;
    }
    [data-testid="stMainBlockContainer"] h3,
    [data-testid="stSidebar"] h3,
    [role="dialog"] h3 {
        font-size: 18px;
        font-weight: 500;
        color: var(--rf-ink);
        padding: 24px 0 8px;
    }
    [data-testid="stSidebar"] {
        border-right: 1px solid var(--rf-line);
    }
    [data-testid="stSidebar"][aria-expanded="true"] { min-width: 288px; }
    [data-testid="stSidebar"] h3 { padding-top: 0; }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary p {
        font-family: var(--rf-mono);
        font-size: 12px;
        color: var(--rf-ink);
        white-space: nowrap;
    }
    [data-testid="stMetricValue"] {
        font-size: 20px;
        font-weight: 500;
        color: var(--rf-ink);
    }
    [data-testid="stMetricLabel"] p { color: var(--rf-ink-3); }
    [data-testid="stBaseButton-primary"],
    [data-testid="stBaseButton-primaryFormSubmit"] {
        background: var(--rf-accent);
        border-color: var(--rf-accent);
        color: #fff;
        transition: background-color 120ms ease-out;
    }
    [data-testid="stBaseButton-primary"]:hover,
    [data-testid="stBaseButton-primaryFormSubmit"]:hover {
        background: #093f86;
        border-color: #093f86;
        color: #fff;
    }
    [data-testid="stMainBlockContainer"] p code {
        font-family: var(--rf-mono);
        color: var(--rf-ink);
        background: var(--rf-raised);
    }
    [data-baseweb="tab-highlight"] { background-color: var(--rf-accent); }
    [data-baseweb="tab"][aria-selected="true"] p { color: var(--rf-accent); }
    [data-testid="stForm"] {
        border: 1px solid var(--rf-line);
        border-radius: 12px;
        padding: 8px 24px 24px;
    }
    .rf-stamp {
        display: inline-block;
        margin: 4px 0 16px;
        padding: 4px 8px;
        font-family: var(--rf-mono);
        font-size: 13px;
        color: var(--rf-ink-2);
        border: 1px solid var(--rf-line);
        border-radius: 4px;
    }
    .rf-stamp span { color: var(--rf-ink-3); }
    .rf-label { font-size: 13px; color: var(--rf-ink-3); margin: 0 0 4px; }
    .rf-ledger, .rf-log { margin: 0; padding: 0; list-style: none; max-width: 720px; }
    .rf-ledger li, .rf-log li {
        display: grid;
        margin: 0;
        padding: 8px 0;
        border-top: 1px solid var(--rf-line);
        color: var(--rf-ink-2);
    }
    .rf-ledger li { grid-template-columns: 40px 1fr 80px; }
    .rf-ledger li span, .rf-ledger li em, .rf-log li span {
        font-family: var(--rf-mono);
        font-size: 13px;
        font-style: normal;
        color: var(--rf-ink-3);
    }
    .rf-ledger li em { text-align: right; }
    .rf-ledger li.rf-done { color: var(--rf-ink); }
    .rf-ledger li.rf-current { color: var(--rf-accent); font-weight: 500; }
    .rf-ledger li.rf-current em { color: var(--rf-accent); }
    .rf-ledger li.rf-pending { color: var(--rf-ink-3); }
    .rf-log li { grid-template-columns: 176px 1fr; }
    .rf-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 24px; margin: 0; max-width: 720px; }
    .rf-fields dt { font-size: 13px; color: var(--rf-ink-3); }
    .rf-fields dd { margin: 0; color: var(--rf-ink); overflow-wrap: anywhere; }
    .rf-figure {
        font-family: var(--rf-mono);
        font-size: 48px;
        font-weight: 500;
        line-height: 1.1;
        font-variant-numeric: tabular-nums;
        color: var(--rf-accent);
    }
    .rf-unit {
        font-family: "Source Sans", sans-serif;
        font-size: 16px;
        color: var(--rf-ink-3);
        margin-left: 8px;
    }
    .rf-meta {
        margin: 4px 0 16px;
        font-family: var(--rf-mono);
        font-size: 13px;
        color: var(--rf-ink-2);
        font-variant-numeric: tabular-nums;
    }
</style>
"""


def _html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def _render_stamp(request_id: str, researcher: dict) -> None:
    """The request's accession stamp: full request ID plus IRB number"""
    irb = (researcher or {}).get("irb_number")
    tail = f" <span>·</span> {html.escape(str(irb))}" if irb else ""
    _html(f'<div class="rf-stamp">{html.escape(str(request_id))}{tail}</div>')


def _render_stage_ledger(current_state: str) -> None:
    current_idx = WORKFLOW_STATES.index(current_state) if current_state in WORKFLOW_STATES else -1
    rows = []
    for idx, state in enumerate(WORKFLOW_STATES):
        # The final stage is an end state, not a stage still in progress.
        if current_idx >= 0 and (idx < current_idx or current_idx == len(WORKFLOW_STATES) - 1):
            cls, mark = "rf-done", "Done"
        elif idx == current_idx:
            cls, mark = "rf-current", "Current"
        else:
            cls, mark = "rf-pending", ""
        rows.append(
            f'<li class="{cls}"><span>{idx + 1:02d}</span>'
            f"{html.escape(_label(state))}<em>{mark}</em></li>"
        )
    _html(f'<ol class="rf-ledger">{"".join(rows)}</ol>')


def _render_activity(activities: list) -> None:
    if not activities:
        st.caption("No agent activity yet")
        return
    rows = []
    for activity in activities:
        when = html.escape(_ts(activity.get("timestamp")) or "N/A")
        agent = html.escape(_label(activity.get("agent", "")))
        task = html.escape(_label(activity.get("task", "")))
        rows.append(f"<li><span>{when}</span>{agent} · {task}</li>")
    _html(f'<ol class="rf-log">{"".join(rows)}</ol>')


def _render_fields(pairs: list) -> None:
    cells = "".join(
        f"<div><dt>{html.escape(k)}</dt><dd>{html.escape(str(v or 'N/A'))}</dd></div>"
        for k, v in pairs
    )
    _html(f'<dl class="rf-fields">{cells}</dl>')


def _render_package(delivery_info: dict) -> None:
    """The delivered package: cohort size as the figure, element and file counts as meta"""
    cohort = int(delivery_info.get("cohort_size") or 0)
    elements = len(delivery_info.get("data_elements", []))
    files = len(delivery_info.get("files", []))
    _html(
        '<div class="rf-label">Cohort size</div>'
        f'<div class="rf-figure">{cohort:,}<span class="rf-unit">patients</span></div>'
        f'<div class="rf-meta">{elements} data element{"" if elements == 1 else "s"}'
        f' · {files} file{"" if files == 1 else "s"}</div>'
    )


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
        ref = log_internal_error(logger, "Error checking delivery status", e)
        st.error(f"Error checking delivery status (ref: {ref})")
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
        ref = log_internal_error(logger, "Download error", e)
        st.error(f"Download error (ref: {ref})")
        return None, None


def show_preview_data_section_researcher(request_id: str, status: dict):
    """Show preview extraction status (not actual data - informatician only)"""
    from app.database.models import DataDelivery
    from sqlalchemy import select
    from app.database import get_db_session

    st.markdown("### Preview extraction")

    try:

        async def get_preview_data():
            async with get_db_session() as session:
                result = await session.execute(
                    select(DataDelivery).where(DataDelivery.request_id == request_id)
                )
                return result.scalar_one_or_none()

        delivery = run_async(get_preview_data())

        if delivery and delivery.preview_data:
            st.success("Preview extraction complete")
            st.caption(
                "The data team extracted a sample preview and is reviewing it before full extraction."
            )

            # Show preview QA status (no actual data)
            if delivery.preview_qa_report:
                qa_report = delivery.preview_qa_report
                st.info(f"Preview QA: {_label(qa_report.get('overall_status', 'unknown'))}")
                st.caption(
                    "The informatician reviews the preview before authorizing full extraction."
                )

        elif status.get("current_state") in ["preview_extraction", "preview_qa"]:
            st.info("Preview data is being extracted and validated. Check back in a few minutes")
        elif status.get("current_state") in [
            "data_extraction",
            "qa_validation",
            "delivery_review",
            "data_delivery",
            "delivered",
            "complete",
        ]:
            st.success("Preview reviewed and approved by the informatician")
            st.caption("Full data extraction is in progress")
        else:
            st.caption("Preview extraction begins after SQL approval")

    except Exception as e:
        st.caption("Preview extraction status not available yet")


@st.dialog("Request details", width="large")
def show_request_details_modal(request_id: str):
    """Show request details in a modal dialog"""

    status = run_async(st.session_state.orchestrator.get_request_status(request_id))

    if not status:
        st.error(f"Request not found: {request_id}")
        return

    researcher = status.get("researcher_info", {})
    _render_stamp(request_id, researcher)

    # Metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Status", _label(status["current_state"]))
    with col2:
        st.metric("Current agent", _agent_label(status.get("current_agent")))
    with col3:
        try:
            started = datetime.fromisoformat(status["started_at"])
            duration = datetime.now() - started
            st.metric("Duration", f"{duration.seconds // 60} min")
        except:
            st.metric("Duration", "N/A")

    st.markdown("### Researcher")
    _render_fields(
        [
            ("Name", researcher.get("name")),
            ("Email", researcher.get("email")),
            ("Department", researcher.get("department")),
            ("IRB number", researcher.get("irb_number")),
        ]
    )

    st.markdown("### Workflow timeline")
    _render_activity(list(reversed((status.get("agents_involved") or [])[-10:])))

    show_preview_data_section_researcher(request_id, status)

    st.markdown("### Data delivery")
    delivery_info = check_delivery_status(request_id)

    # Only show "ready" if files actually exist
    if delivery_info.get("delivered") and len(delivery_info.get("files", [])) > 0:
        st.success("Data ready for download")
        _render_package(delivery_info)
        st.caption("Download the files from the Request details tab")
    elif delivery_info.get("delivered") and len(delivery_info.get("files", [])) == 0:
        # Delivery record exists but no files (delivery_agent didn't execute properly)
        st.warning("Delivery started, but the files are not available yet")
        st.caption("The delivery process may have hit an issue. Contact support if this persists.")

        st.markdown("### Schedule a kickoff meeting (optional)")
        st.caption("Meet the data team to discuss your dataset")

        if st.button(
            "Schedule meeting",
            icon=":material/event:",
            type="secondary",
            use_container_width=True,
            key=f"schedule_meeting_{request_id}",
        ):
            # DISABLED: trigger_agent_task() not supported with LangGraph
            st.warning(
                "Meeting scheduling is not available in the LangGraph workflow. "
                "Contact the data team directly to schedule a meeting."
            )
            st.caption("Data team: data-team@hospital.org")
    else:
        st.info(f"Not delivered yet. Current stage: {_label(status['current_state'])}")

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
        page_title="ResearchFlow - Data Request Portal",
        page_icon=":material/assignment:",
        layout="wide",
    )
    # Page-scoped styles (#363). The shared .streamlit/config.toml theme also
    # styles the exploratory and admin dashboards, so this page overrides it locally.
    _html(_CSS)

    # Initialize orchestrator
    initialize_orchestrator()

    st.title("Request a dataset for your study")
    st.caption(
        "Describe the cohort and the data you need. An informatician reviews the "
        "cohort SQL before extraction, and the data passes QA before delivery."
    )

    # Sidebar - My Requests
    with st.sidebar:
        st.markdown("### My requests")

        # Initialize session state
        if "user_requests" not in st.session_state:
            st.session_state.user_requests = []  # Track just-submitted requests
        if "researcher_email_input" not in st.session_state:
            st.session_state.researcher_email_input = load_researcher_email()

        researcher_email = st.text_input(
            "Your email",
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

        st.divider()

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
                    count = len(db_requests)
                    st.caption(f"{count} request{'' if count == 1 else 's'}")

                    for status in db_requests:
                        req_id = status["request_id"]

                        badge = get_status_badge(status["current_state"])
                        new_indicator = " · new" if req_id in just_submitted_ids else ""

                        with st.expander(f"{badge} {req_id}{new_indicator}"):
                            st.markdown(_label(status["current_state"]))
                            st.caption(f"Started {_ts(status['started_at'])}")

                            # Show cohort size if delivered
                            delivery_info = check_delivery_status(req_id)
                            if delivery_info.get("delivered"):
                                files = len(delivery_info.get("files", []))
                                st.caption(
                                    f"Cohort {int(delivery_info.get('cohort_size') or 0):,} patients"
                                    f" · {files} file{'' if files == 1 else 's'} ready"
                                )

                            if st.button("View details", key=f"view_{req_id}"):
                                st.session_state.modal_request = req_id
                                # Issue #35: also select this request so the
                                # "Request details" tab (and its download UI)
                                # resolves for a returning researcher who never
                                # submitted in this browser session. Previously
                                # only new-request submission set selected_request,
                                # so the modal's "go to Request details tab" hint
                                # was a dead pointer after a page refresh.
                                st.session_state.selected_request = req_id
                                # Remove from "just submitted" set after viewing
                                if req_id in just_submitted_ids:
                                    st.session_state.user_requests.remove(req_id)

                    # Show modal if a request was clicked
                    if st.session_state.get("modal_request"):
                        show_request_details_modal(st.session_state.modal_request)
                else:
                    st.caption("No requests for this email yet")

            except Exception as e:
                ref = log_internal_error(logger, "Error loading requests", e)
                st.error(f"Error loading requests (ref: {ref})")
        else:
            st.caption("Enter your email to see your requests")

    # Main content area
    tab1, tab2 = st.tabs(["New request", "Request details"])

    with tab1:
        show_new_request_form()

    with tab2:
        show_request_details()


def show_new_request_form():
    """Display new request submission form"""
    with st.form("researcher_info"):
        st.markdown("### Researcher")

        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Name *", placeholder="Dr. Jane Smith")
            department = st.text_input("Department", placeholder="Cardiology")

        with col2:
            email = st.text_input("Email *", placeholder="jsmith@hospital.edu")
            irb_number = st.text_input("IRB number *", placeholder="IRB-2024-001")

        st.markdown("### Request")
        request_text = st.text_area(
            "Describe your data needs *",
            placeholder="Example: I need clinical notes and lab results for heart failure patients admitted in 2024 who had a prior diabetes diagnosis.",
            height=100,
        )

        st.markdown("### Study criteria")

        col1, col2 = st.columns(2)
        with col1:
            inclusion_criteria = st.text_area(
                "Inclusion criteria",
                placeholder="Example:\n- Age >= 18 years\n- Diagnosed with diabetes\n- Admitted in 2024",
                height=100,
                help="One inclusion criterion per line",
            )

        with col2:
            exclusion_criteria = st.text_area(
                "Exclusion criteria",
                placeholder="Example:\n- Pregnant patients\n- Age < 18 years",
                height=100,
                help="One exclusion criterion per line",
            )

        st.markdown("### Time period")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input(
                "Start date", value=None, help="Start of the data collection period"
            )
        with col2:
            end_date = st.date_input(
                "End date", value=None, help="End of the data collection period"
            )

        st.markdown("### Data elements")
        data_elements = st.multiselect(
            "Select data elements needed",
            # Only elements extraction can deliver (#205); the list lives next to the dispatch.
            options=FORM_DATA_ELEMENTS,
            default=[FORM_DATA_ELEMENTS[0]],
            help="Select every data type your study needs",
        )

        st.markdown("### Privacy level")
        phi_level = st.selectbox(
            "PHI level *",
            options=[
                "De-identified (HIPAA Safe Harbor)",
                "Limited Dataset (dates allowed)",
                "Identified (full PHI)",
            ],
            index=0,
            help="The level of patient identifiers your study needs",
        )

        submit = st.form_submit_button("Submit request", type="primary")

        if submit:
            if not all([name, email, irb_number, request_text]):
                st.error("Fill in the required fields: name, email, IRB number and data needs")
            else:
                # Submit request
                with st.spinner("Submitting the request. This takes 30 to 60 seconds"):
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
                                "Request processing timed out after 2 minutes. Try again, or contact support if it keeps happening."
                            )
                            return

                        # Add to session state
                        if "user_requests" not in st.session_state:
                            st.session_state.user_requests = []
                        st.session_state.user_requests.append(request_id)

                        st.success(f"Request submitted: {request_id}")

                        # Switch to details tab
                        st.session_state.selected_request = request_id

                    except Exception as e:
                        ref = log_internal_error(logger, "Failed to submit request", e)
                        st.error(f"Failed to submit request (ref: {ref})")


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

    researcher = status.get("researcher_info", {})
    _render_stamp(request_id, researcher)

    # Status overview
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Status", _label(status["current_state"]))
    with col2:
        st.metric("Current agent", _agent_label(status.get("current_agent")))
    with col3:
        started = datetime.fromisoformat(status["started_at"])
        duration = datetime.now() - started
        st.metric("Duration", f"{duration.seconds // 60} min")

    st.markdown("### Workflow progress")
    _render_stage_ledger(status["current_state"])

    st.markdown("### Agent activity")
    _render_activity(list(reversed(status.get("agents_involved") or [])))

    st.markdown("### Researcher")
    _render_fields(
        [
            ("Name", researcher.get("name")),
            ("Email", researcher.get("email")),
            ("IRB number", researcher.get("irb_number")),
        ]
    )

    st.markdown("### Data delivery")

    delivery_info = check_delivery_status(request_id)

    if delivery_info.get("delivered"):
        st.success("Your data is ready for download")
        _render_package(delivery_info)

        st.markdown("### Download options")

        st.markdown("**Complete package (ZIP)**")
        st.caption("All data files, the data dictionary, the QA report and documentation")

        if st.button(
            "Download complete package",
            icon=":material/download:",
            type="primary",
            use_container_width=True,
        ):
            with st.spinner("Preparing download"):
                file_content, filename = download_file(request_id)
                if file_content:
                    st.download_button(
                        label="Save ZIP file",
                        icon=":material/save:",
                        data=file_content,
                        file_name=filename,
                        mime="application/zip",
                        type="primary",
                        use_container_width=True,
                    )
                    st.success(f"Ready to download: {filename}")

        st.markdown("**Individual files**")

        files = delivery_info.get("files", [])
        if files:
            for file_info in files:
                filename = file_info.get("filename", "unknown.csv")
                file_size = file_info.get("size_mb", 0)

                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"`{filename}` · {file_size:.2f} MB")
                with col2:
                    if st.button("Download", key=f"dl_{filename}", use_container_width=True):
                        with st.spinner(f"Downloading {filename}"):
                            file_content, _ = download_file(request_id, filename)
                            if file_content:
                                st.download_button(
                                    label=f"Save {filename}",
                                    data=file_content,
                                    file_name=filename,
                                    mime="text/csv" if filename.endswith(".csv") else "text/plain",
                                    key=f"save_{filename}",
                                    use_container_width=True,
                                )
        else:
            st.caption("No files available for download")

        # QA Summary
        if delivery_info.get("qa_report_summary"):
            st.markdown("### Quality assurance summary")
            qa_summary = delivery_info["qa_report_summary"]
            st.json(qa_summary)

    else:
        # Not yet delivered
        current_state = status["current_state"]
        info = _state_info(current_state)
        if info is not None and info.kind is StateKind.SUCCEEDED:
            st.warning("Data delivery is being prepared. Check back in a few minutes")
        elif current_state in (
            WorkflowState.DATA_EXTRACTION.value,
            WorkflowState.QA_VALIDATION.value,
            WorkflowState.DATA_DELIVERY.value,
        ):
            st.info(f"Your request is being processed. Current stage: {_label(current_state)}")
            st.caption("You can download your data once processing completes")
        elif current_state == WorkflowState.NOT_FEASIBLE.value:
            st.warning(
                "The request was found not feasible. Review the feedback and submit a new request"
            )
        elif info is not None and info.kind is StateKind.FAILED:
            # Fixed text: research_requests.error_message holds raw failure output.
            st.error("The request did not complete. Contact support for help")
        elif info is not None and info.kind is StateKind.AWAITING_REVIEW:
            st.info(f"Waiting for review: {info.label}")
            st.caption("Data download opens once the request is completed and delivered")
        else:
            st.info(f"In progress: {_label(current_state)}")
            st.caption("Data download opens once the request is completed and delivered")


if __name__ == "__main__":
    main()
