"""
Research Notebook - Conversational Research Workflow

Two-stage workflow:
1. Feasibility Check (SQL-on-FHIR) - Fast, no PHI, counts only
2. Data Extraction (Orchestrator) - Full workflow with approvals

Features:
- Conversational AI with intent detection
- Summary statistics before extraction
- Approval workflow integration
- Real-time status tracking
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

# NOW safe to import modules
import streamlit as st

import html
import logging
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv

# Set up logging
logger = logging.getLogger(__name__)

# Load environment variables from project root (explicit path)
# Get project root: /Users/.../FHIR_PROJECT
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
dotenv_path = os.path.join(project_root, ".env")

# Load .env file
load_dotenv(dotenv_path)

# Verify critical environment variables are loaded
anthropic_key = os.getenv("ANTHROPIC_API_KEY")
if anthropic_key:
    print(
        f"✓ Loaded ANTHROPIC_API_KEY from: {dotenv_path} (key starts with: {anthropic_key[:20]}...)"
    )
else:
    print(f"⚠️  WARNING: ANTHROPIC_API_KEY not found! Checked: {dotenv_path}")
    print(f"   Query interpretation will fall back to dummy mode (inaccurate results)")

# Add parent directory to path
sys.path.insert(0, project_root)

# Phase 3b CSO Finding 2: streamlit processes start outside the FastAPI lifespan,
# so the encryption-key gate must run independently here. Without this call, a
# typo'd ENCRYPTION_KEY_PRIMARY in production surfaces only on the first PHI
# access as cryptography.fernet.InvalidToken inside a SQLAlchemy result-processor
# stack frame — burying the misconfiguration. With this call, the dashboard
# refuses to start and emits the same clean RuntimeError as `uvicorn`.
from app.security.encryption_keys import assert_encryption_key_present_if_production
from app.schemas._errors import log_internal_error
from app.portal_urls import FORMAL_PORTAL_URL

assert_encryption_key_present_if_production()

from app.services.conversation_manager import ConversationManager, UserIntent, ConversationState
from app.services.feasibility_service import FeasibilityService
from app.components.approval_tracker import ApprovalTracker
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade


def run_async(coroutine):
    """
    Run async code in Streamlit's persistent event loop.

    Uses the loop set up at module import time to ensure all
    database operations use the same loop.
    """
    return _streamlit_loop.run_until_complete(coroutine)


# Page config
st.set_page_config(
    page_title="ResearchFlow - Interactive Research Assistant",
    page_icon=":material/query_stats:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Page-scoped styles (#362). The shared .streamlit/config.toml theme also
# styles the formal and admin dashboards, so this page overrides it locally.
st.markdown(
    """
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
    [data-testid="stSidebar"] {
        border-right: 1px solid var(--rf-line);
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {
        justify-content: flex-start;
        text-align: left;
        min-height: 36px;
        padding: 8px 12px;
        border: 1px solid var(--rf-line);
        border-radius: 8px;
        color: var(--rf-ink-2);
        background: #fff;
        transition: background-color 120ms ease-out, color 120ms ease-out;
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover {
        background: var(--rf-raised);
        border-color: var(--rf-line);
        color: var(--rf-ink);
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] p {
        text-align: left;
    }
    [data-testid="stChatMessage"] {
        background: transparent;
        padding: 16px 0;
        border-bottom: 1px solid var(--rf-line);
        border-radius: 0;
    }
    [data-testid="stChatMessage"] [data-testid^="stChatMessageAvatar"] {
        background: var(--rf-raised);
        color: var(--rf-ink-2);
        border: 1px solid var(--rf-line);
    }
    .rf-brand { font-size: 18px; font-weight: 500; color: var(--rf-ink); }
    .rf-sub, .rf-label { font-size: 13px; color: var(--rf-ink-3); }
    .rf-sub { margin-bottom: 24px; }
    .rf-label { margin: 24px 0 8px; }
    .rf-mono { font-family: var(--rf-mono); font-size: 13px; color: var(--rf-ink-2); }
    .rf-steps { margin: 32px 0 0; padding: 0; list-style: none; max-width: 640px; }
    .rf-steps li {
        display: grid;
        grid-template-columns: 32px 1fr;
        margin: 0;
        padding: 12px 0;
        border-top: 1px solid var(--rf-line);
        color: var(--rf-ink-2);
    }
    .rf-steps li span { font-family: var(--rf-mono); color: var(--rf-ink-3); }
    .rf-result { padding: 4px 0 8px; }
    .rf-result .rf-label { margin: 0 0 4px; }
    .rf-figure {
        font-family: var(--rf-mono);
        font-size: 56px;
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
    .rf-criteria { margin-top: 8px; color: var(--rf-ink); max-width: 640px; }
    .rf-stamp {
        display: inline-block;
        margin-top: 12px;
        padding: 2px 8px;
        font-family: var(--rf-mono);
        font-size: 12px;
        color: var(--rf-ink-3);
        border: 1px solid var(--rf-line);
        border-radius: 4px;
    }
</style>
""",
    unsafe_allow_html=True,
)


def initialize_session_state():
    """Initialize session state variables"""
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Conversation manager for intent detection
    if "conversation_manager" not in st.session_state:
        st.session_state.conversation_manager = ConversationManager()

    # Conversation state tracking
    if "conversation_state" not in st.session_state:
        st.session_state.conversation_state = ConversationState.INITIAL

    if "feasibility_service" not in st.session_state:
        st.session_state.feasibility_service = FeasibilityService()

    if "approval_tracker" not in st.session_state:
        st.session_state.approval_tracker = ApprovalTracker()

    if "pending_feasibility" not in st.session_state:
        st.session_state.pending_feasibility = None

    if "pending_request_id" not in st.session_state:
        st.session_state.pending_request_id = None

    if "last_query_intent" not in st.session_state:
        st.session_state.last_query_intent = None

    # Session ID for conversation tracking
    if "session_id" not in st.session_state:
        st.session_state.session_id = f"notebook_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


async def handle_user_input(user_input: str):
    """
    Handle user input with conversational AI and intent detection

    EXPLORATORY MODE:
    - Conversational AI with intent detection
    - Quick feasibility checks (SQL-on-FHIR)
    - Routes to formal portal for full extraction
    """
    # Detect intent using ConversationManager
    intent = await st.session_state.conversation_manager.detect_intent(user_input)

    # Route based on intent
    if intent == UserIntent.GREETING:
        # User greeted us
        response = st.session_state.conversation_manager.get_introduction()
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.session_state.conversation_state = ConversationState.INITIAL

    elif intent == UserIntent.HELP:
        # User needs help
        response = st.session_state.conversation_manager.get_help_message()
        st.session_state.messages.append({"role": "assistant", "content": response})

    elif intent == UserIntent.CONFIRMATION:
        # User confirmed something - check what they're confirming
        if st.session_state.conversation_state == ConversationState.AWAITING_CONFIRMATION:
            # User confirmed feasibility results - direct to formal portal
            if await st.session_state.conversation_manager.is_confirmation(user_input):
                response = f"""### Take this to the Formal Portal

1. Open the Formal Portal at {FORMAL_PORTAL_URL}
2. Fill in the research request form
3. Use this count to size the request

The Formal Portal runs informatician review, data extraction, QA and delivery, with a full audit trail. This portal only returns counts."""
            else:
                # User rejected - offer to refine
                response = "Tell me what to change in the criteria."
                st.session_state.conversation_state = ConversationState.INITIAL

            st.session_state.messages.append({"role": "assistant", "content": response})
        else:
            # No pending confirmation
            response = "There is no count to confirm yet. Ask a question about the patient population first."
            st.session_state.messages.append({"role": "assistant", "content": response})

    elif intent == UserIntent.STATUS_CHECK:
        # User checking status
        if st.session_state.pending_request_id:
            response = f"""### Request Status

**Request ID:** {st.session_state.pending_request_id}

Check detailed status in the **Formal Request Portal** at {FORMAL_PORTAL_URL}

Full request tracking is in the Formal Portal."""
        else:
            response = "You have no pending requests. Ask a question about the patient population to start."

        st.session_state.messages.append({"role": "assistant", "content": response})

    elif intent == UserIntent.QUERY:
        # Data query - route to SQL execution
        await handle_query(user_input)

    else:
        # Unknown intent - provide guidance
        response = """I can help you with:
- **Data queries**: "How many patients with diabetes?"
- **Status checks**: "What's my request status?"
- **Help**: "What can you do?\""""
        st.session_state.messages.append({"role": "assistant", "content": response})


def _freshness_caption(feasibility_data: Dict[str, Any]) -> str:
    """'data as of <ts>' disclosure (#97). The exploratory portal reads
    batch-only MVs; make the staleness explicit instead of implicit. Empty
    string when no anchor is available (e.g. legacy path or unrefreshed views)."""
    anchor = feasibility_data.get("batch_anchor_ts")
    if not anchor:
        return ""
    ts = str(anchor).replace("T", " ")[:19]  # ISO → "YYYY-MM-DD HH:MM:SS"
    return f"Data as of {ts} (batch snapshot)"


def _render_freshness(feasibility_data: Dict[str, Any]) -> None:
    caption = _freshness_caption(feasibility_data)
    if caption:
        st.caption(caption)


def _error_card_markdown(feasibility_data: Dict[str, Any]) -> str:
    """The honest-error variant (#96) as chat markdown — explanation + reason +
    the rejected SQL, NEVER a fabricated cohort count."""
    explanation = feasibility_data.get("explanation") or "The query could not be run."
    reason = feasibility_data.get("reason", "unknown reason")
    rejected_sql = feasibility_data.get("rejected_sql", "")
    parts = [
        "## Query could not be run",
        "",
        f"**What was attempted:** {explanation}",
        "",
        f"**Why it was rejected:** {reason}",
    ]
    if rejected_sql:
        parts += ["", "**Rejected SQL:**", "```sql", rejected_sql, "```"]
    parts += ["", "_No cohort estimate is shown. An error never renders as a count._"]
    return "\n".join(parts)


def _render_error_card(feasibility_data: Dict[str, Any]) -> None:
    st.error("Query could not be run, so there is no cohort estimate")
    st.markdown(f"**What was attempted:** {feasibility_data.get('explanation', '—')}")
    st.markdown(f"**Why it was rejected:** {feasibility_data.get('reason', 'unknown reason')}")
    rejected_sql = feasibility_data.get("rejected_sql")
    if rejected_sql:
        st.markdown("**Rejected SQL:**")
        st.code(rejected_sql, language="sql")


async def handle_query(user_input: str):
    """
    Handle research query

    Two-stage workflow:
    1. Feasibility check (SQL-on-FHIR) - Fast COUNT query
    2. Show results and ask for confirmation
    """
    # Show status
    with st.status("Working on your question", expanded=True) as status:
        # #100: the synthesis path reads the raw NL directly (NL -> LLM SQL ->
        # validate -> execute inside execute_feasibility_check). The legacy
        # QueryInterpreter/QueryIntent pre-parse was retired; query_intent is
        # kept only as a vestigial carrier (no UI source for time_period → {}).
        st.write("Writing SQL for your question")
        query_intent = {}

        # Step 2: Execute feasibility check (LLM-synthesized COUNT query)
        # IMPORTANT: Close old connection pool before query to avoid event loop conflicts
        try:
            await st.session_state.feasibility_service.close()
        except Exception as e:
            log_internal_error(
                logger, "Failed to close old feasibility service", e, level=logging.WARNING
            )

        # Create fresh FeasibilityService with new connection pool
        st.session_state.feasibility_service = FeasibilityService()

        st.write("Running the count on the batch views")
        feasibility_data = await st.session_state.feasibility_service.execute_feasibility_check(
            query_intent,
            # #100: raw NL is the synthesis input — the researcher's actual words,
            # not a lossy intent dict.
            natural_language_query=user_input,
        )
        # #96/#97: the synthesis path returns an explicit error variant on
        # validator rejection / execution failure. NEVER render a fabricated
        # "0 patients" for an error — show the honest error card and stop.
        if feasibility_data.get("status") == "error":
            status.update(label="Query could not be run", state="error")
            _render_error_card(feasibility_data)
            st.session_state.messages.append(
                {"role": "assistant", "content": _error_card_markdown(feasibility_data)}
            )
            # Clear any prior successful result so the sidebar Details tab can't
            # show a stale cohort after a failed query.
            st.session_state.pending_feasibility = None
            st.session_state.conversation_state = ConversationState.INITIAL
            return

        st.write(f"Counted {feasibility_data['estimated_cohort']:,} patients")
        _render_freshness(feasibility_data)

        status.update(label="Count ready", state="complete")

    # Store for later
    st.session_state.pending_feasibility = feasibility_data
    st.session_state.last_query_intent = query_intent

    # #100: the synthesis path returns a single scalar count (or the honest-error
    # variant, handled above). Breakdown / count-distinct result shapes belonged
    # to the retired legacy path and are never produced now.
    # The message carries the result itself, so every count keeps its own SQL
    # and anchor; content is the plain-text fallback.
    cohort_size = feasibility_data["estimated_cohort"]
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": f"Estimated cohort: {cohort_size:,} patients",
            "result": feasibility_data,
        }
    )

    # Set conversation state to awaiting confirmation
    st.session_state.conversation_state = ConversationState.AWAITING_CONFIRMATION


def _formal_facade() -> LangGraphRequestFacade:
    if "formal_facade" not in st.session_state:
        st.session_state.formal_facade = LangGraphRequestFacade(
            use_real_agents=True, use_persistence=True
        )
    return st.session_state.formal_facade


async def start_formal_request(
    facade: LangGraphRequestFacade, initial_request: str, structured_requirements: Dict[str, Any]
) -> str:
    """Create the formal request and start its LangGraph workflow, in-process,
    as the formal portal does (#273). The old /research/submit +
    /research/process hand-off never started a workflow."""
    return await facade.process_new_request(
        researcher_request=initial_request,
        researcher_info={
            "name": "Research Notebook User",
            "email": "researcher@hospital.org",
            "department": "Clinical Research",
            "irb_number": "IRB-NOTEBOOK-001",
            "structured_requirements": structured_requirements,
        },
        from_formal_portal=True,
    )


def formal_structured_requirements(feasibility_data: Dict[str, Any]) -> Dict[str, Any]:
    """What the notebook knows about a confirmed query, for the formal workflow.

    No criteria or data-element keys: the exploratory path has no parsed
    criteria (QueryIntent was retired in #100), and an empty list would
    override the requirements agent's fallback to the query text (#273).
    Blank dates mean no time filter.
    """
    return {
        "study_title": f"Research Notebook Query - {datetime.now().strftime('%Y-%m-%d')}",
        "principal_investigator": "Research Notebook User",
        "time_period": feasibility_data.get("time_period") or {"start": None, "end": None},
        "estimated_cohort_size": feasibility_data.get("estimated_cohort"),
        "delivery_format": "CSV",
        "phi_level": "de-identified",
    }


async def submit_research_request():
    """Start the confirmed query as a formal request (LangGraph workflow)."""
    try:
        structured_requirements = formal_structured_requirements(
            st.session_state.pending_feasibility
        )

        # The user's original query is the message before the confirmation.
        # Same bound as the formal portal's submit (2 minutes).
        request_id = await asyncio.wait_for(
            start_formal_request(
                _formal_facade(), st.session_state.messages[-2]["content"], structured_requirements
            ),
            timeout=120.0,
        )
        st.session_state.pending_request_id = request_id

        # Show confirmation message
        confirmation_message = f"""### Request submitted

**Request ID:** `{request_id}`

It is now in the approval workflow:

1. Requirements extracted
2. **Waiting for informatician SQL review**
3. Data extraction, after approval
4. Quality assurance
5. Data delivery

Review usually takes 1 to 24 hours, depending on informatician availability. Type **status** to check progress. You can keep asking questions here while you wait."""

        st.session_state.messages.append({"role": "assistant", "content": confirmation_message})

    except Exception as e:
        ref = log_internal_error(logger, "Error submitting request", e)
        error_message = (
            f"**Could not submit the request** (ref: {ref}).\n\n"
            "Please try again or contact support with that reference."
        )
        st.session_state.messages.append({"role": "assistant", "content": error_message})


EXAMPLE_QUERIES = [
    "How many patients are available?",
    "Patients with diabetes and HbA1c > 8%",
    "Female patients with hypertension under 65",
]

SMALL_COHORT = 30


def render_sidebar():
    """Render sidebar"""
    with st.sidebar:
        st.markdown(
            '<div class="rf-brand">ResearchFlow</div>'
            '<div class="rf-sub">Exploratory portal · counts only</div>',
            unsafe_allow_html=True,
        )

        st.markdown('<div class="rf-label">Try a question</div>', unsafe_allow_html=True)
        for example in EXAMPLE_QUERIES:
            if st.button(example, key=f"ex_{example[:20]}", use_container_width=True):
                st.session_state.example_query = example
                st.rerun()

        if st.session_state.pending_request_id:
            st.markdown(
                '<div class="rf-label">Active request</div>'
                f'<div class="rf-mono">{html.escape(str(st.session_state.pending_request_id))}</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<div class="rf-label">Patient rows</div>', unsafe_allow_html=True)
        st.caption(
            "This portal returns counts only. Extracting patient data goes through "
            f"informatician review in the [Formal Portal]({FORMAL_PORTAL_URL})"
        )

        st.markdown('<div class="rf-label"></div>', unsafe_allow_html=True)
        if st.button("Clear conversation", icon=":material/delete:", type="tertiary"):
            st.session_state.messages = []
            st.session_state.pending_feasibility = None
            st.session_state.pending_request_id = None
            st.session_state.last_query_intent = None
            st.session_state.conversation_state = ConversationState.INITIAL
            st.rerun()


def _render_steps() -> None:
    """Empty state: how a count is made (ADR 0028), so the first screen says
    what the portal will and won't return."""
    st.markdown(
        '<ol class="rf-steps">'
        "<li><span>1</span>Claude writes SQL for your question</li>"
        "<li><span>2</span>A validator lets through aggregate counts only, never patient rows</li>"
        "<li><span>3</span>The count runs read-only on the batch views and says when they were refreshed</li>"
        "</ol>",
        unsafe_allow_html=True,
    )


def _render_result(feasibility_data: Dict[str, Any], is_last: bool) -> None:
    """A successful count: the figure, what it counted, its batch anchor and
    the SQL that ran. Only ever called for status == "ok" (#96)."""
    cohort = feasibility_data["estimated_cohort"]
    stamp = _freshness_caption(feasibility_data)
    criteria = feasibility_data.get("filter_summary") or ""
    st.markdown(
        '<div class="rf-result">'
        '<div class="rf-label">Estimated cohort</div>'
        f'<div class="rf-figure">{cohort:,}<span class="rf-unit">patients</span></div>'
        + (f'<div class="rf-criteria">{html.escape(criteria)}</div>' if criteria else "")
        + (f'<span class="rf-stamp">{html.escape(stamp)}</span>' if stamp else "")
        + "</div>",
        unsafe_allow_html=True,
    )
    if cohort < SMALL_COHORT:
        st.caption(f"Fewer than {SMALL_COHORT} patients. Consider broadening the criteria")

    sql = feasibility_data.get("generated_sql")
    if sql:
        with st.expander("SQL that ran"):
            st.code(sql, language="sql")
            st.caption(f"{feasibility_data.get('execution_time_ms') or 0:.1f} ms · read-only")

    if is_last:
        st.markdown(
            "Type **proceed** to see how to take this to the Formal Portal, or refine the question"
        )


def main():
    """Main application"""
    # Initialize
    initialize_session_state()

    st.title("Count a cohort before you request it")
    st.caption(
        "Ask in plain words. You get an aggregate patient count from the "
        "SQL-on-FHIR batch views, never patient rows."
    )

    render_sidebar()

    if not st.session_state.messages:
        _render_steps()

    last = len(st.session_state.messages) - 1
    for idx, message in enumerate(st.session_state.messages):
        if message["role"] == "user":
            with st.chat_message("user", avatar=":material/person:"):
                st.markdown(message["content"])
        else:
            with st.chat_message("assistant", avatar=":material/query_stats:"):
                if message.get("result"):
                    _render_result(message["result"], is_last=idx == last)
                else:
                    st.markdown(message["content"])

    user_input = st.chat_input("Ask a cohort question")

    # Handle example query from sidebar
    if "example_query" in st.session_state:
        user_input = st.session_state.example_query
        del st.session_state.example_query

    # Process user input
    if user_input:
        # Add user message
        st.session_state.messages.append({"role": "user", "content": user_input})

        # Handle input
        run_async(handle_user_input(user_input))

        # Rerun to show new messages
        st.rerun()


if __name__ == "__main__":
    main()
