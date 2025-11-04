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
import httpx
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

from app.services.conversation_manager import ConversationManager, UserIntent, ConversationState
from app.services.feasibility_service import FeasibilityService
from app.services.query_interpreter import QueryInterpreter
from app.components.approval_tracker import ApprovalTracker


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
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown(
    """
<style>
    .chat-message {
        padding: 1.5rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        display: flex;
        flex-direction: column;
    }
    .user-message {
        background-color: #e3f2fd;
        border-left: 5px solid #2196f3;
    }
    .assistant-message {
        background-color: #f5f5f5;
        border-left: 5px solid #4caf50;
    }
    .feasibility-card {
        background-color: #fff;
        border: 2px solid #1f77b4;
        border-radius: 10px;
        padding: 20px;
        margin: 15px 0;
    }
    .warning-box {
        background-color: #fff3cd;
        border-left: 5px solid #ffc107;
        padding: 15px;
        margin: 10px 0;
        border-radius: 5px;
    }
    .success-box {
        background-color: #d4edda;
        border-left: 5px solid #28a745;
        padding: 15px;
        margin: 10px 0;
        border-radius: 5px;
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

    if "query_interpreter" not in st.session_state:
        st.session_state.query_interpreter = QueryInterpreter()

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
    intent = st.session_state.conversation_manager.detect_intent(user_input)

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
            if st.session_state.conversation_manager.is_confirmation(user_input):
                response = """### ✅ Great! Let's move to the Formal Portal

**Next Steps:**
1. Open the **Formal Request Portal** at http://localhost:8501
2. Fill out the complete research request form
3. Your feasibility results will help inform the request

**What the Formal Portal Provides:**
- Full approval workflow with informaticians
- Data extraction and QA validation
- Secure data delivery
- Complete audit trail

*The Exploratory Portal is designed for fast feasibility checks only. Full data extraction requires the formal approval workflow.*"""
            else:
                # User rejected - offer to refine
                response = "No problem! Would you like to refine your search criteria? Just tell me what you'd like to change."
                st.session_state.conversation_state = ConversationState.INITIAL

            st.session_state.messages.append({"role": "assistant", "content": response})
        else:
            # No pending confirmation
            response = "I'm not sure what you're confirming. Could you ask a specific question about patient data?"
            st.session_state.messages.append({"role": "assistant", "content": response})

    elif intent == UserIntent.STATUS_CHECK:
        # User checking status
        if st.session_state.pending_request_id:
            response = f"""### Request Status

**Request ID:** {st.session_state.pending_request_id}

Check detailed status in the **Formal Request Portal** at http://localhost:8501

*Tip: The Exploratory Portal is for feasibility checks only. Full request tracking is in the Formal Portal.*"""
        else:
            response = "You don't have any pending requests. Ask me a question about patient data to get started!"

        st.session_state.messages.append({"role": "assistant", "content": response})

    elif intent == UserIntent.QUERY:
        # Data query - route to SQL execution
        await handle_query(user_input)

    else:
        # Unknown intent - provide guidance
        response = """I can help you with:
- **Data queries**: "How many patients with diabetes?"
- **Status checks**: "What's my request status?"
- **Help**: "What can you do?"

Try asking a question about patient data!"""
        st.session_state.messages.append({"role": "assistant", "content": response})


def format_breakdown_response(feasibility_data: Dict[str, Any]) -> str:
    """
    Format breakdown query results with total and per-dimension counts

    Args:
        feasibility_data: Feasibility data with breakdown_results

    Returns:
        Formatted markdown string
    """
    total_count = feasibility_data["estimated_cohort"]
    breakdown_results = feasibility_data.get("breakdown_results", [])
    group_by_dimensions = feasibility_data.get("group_by_dimensions", [])

    # Start with header
    response_parts = [
        "## Feasibility Analysis (Breakdown)",
        "",
        f"**Total Cohort Size**: {total_count} patients",
        "",
    ]

    # Add breakdown by dimensions
    if breakdown_results:
        # Format dimension names
        dimension_label = " and ".join(
            [dim.title().replace("_", " ") for dim in group_by_dimensions]
        )
        response_parts.append(f"**Breakdown by {dimension_label}**:")
        response_parts.append("")

        # Add each dimension result
        for result in breakdown_results:
            dimensions = result.get("dimensions", {})
            count = result.get("count", 0)
            percentage = result.get("percentage", 0)

            # Format dimension values
            dim_values = []
            for dim_name, dim_value in dimensions.items():
                if dim_value is not None:
                    # Capitalize and format dimension value
                    formatted_value = (
                        str(dim_value).title() if isinstance(dim_value, str) else str(dim_value)
                    )
                    dim_values.append(f"{dim_name.replace('_', ' ').title()}: {formatted_value}")

            dim_label = ", ".join(dim_values) if dim_values else "Unknown"
            response_parts.append(f"- **{dim_label}**: {count} patients ({percentage}%)")

        response_parts.append("")

    # Add status indicator
    if total_count >= 30:
        response_parts.append("✅ This appears to be a good cohort size for your study.")
    else:
        response_parts.append("⚠️ Small cohort size - consider broadening criteria.")

    response_parts.append("")
    response_parts.append("**Next Steps:**")
    response_parts.append(
        '- Type **"proceed"** to submit to the Formal Portal for full data extraction'
    )
    response_parts.append("- Or ask another question to refine your search")

    return "\n".join(response_parts)


def format_count_distinct_response(feasibility_data: Dict[str, Any]) -> str:
    """
    Format count distinct query results

    Args:
        feasibility_data: Feasibility data with count_distinct results

    Returns:
        Formatted markdown string
    """
    distinct_count = feasibility_data["estimated_cohort"]
    resource_type = feasibility_data.get("resource_type", "resources")
    distinct_column = feasibility_data.get("distinct_column", "unknown")

    # Start with header
    response_parts = [
        "## Count Distinct Results",
        "",
        f"**Found {distinct_count} distinct {resource_type}** in the database",
        "",
    ]

    # Add technical details
    response_parts.append(f"*Counted unique values in column: `{distinct_column}`*")
    response_parts.append("")

    # Add warnings if present
    warnings = feasibility_data.get("warnings", [])
    if warnings:
        response_parts.append("### ⚠️ Notes:")
        for warning in warnings:
            response_parts.append(f"- {warning['message']}")
        response_parts.append("")

    # Add status indicator
    if distinct_count == 0:
        response_parts.append("❌ No distinct values found - try broadening your search criteria.")
    elif distinct_count < 5:
        response_parts.append("⚠️ Very few distinct values found.")
    else:
        response_parts.append("✅ Results found successfully.")

    return "\n".join(response_parts)


async def handle_query(user_input: str):
    """
    Handle research query

    Two-stage workflow:
    1. Feasibility check (SQL-on-FHIR) - Fast COUNT query
    2. Show results and ask for confirmation
    """
    # Show status
    with st.status("Processing your query...", expanded=True) as status:
        # Step 1: Interpret query using LLM
        st.write("🔍 Analyzing your research question...")
        query_intent = await st.session_state.query_interpreter.interpret_query(user_input)
        st.write(f"✅ Identified criteria and data elements")

        # Step 2: Execute feasibility check (SQL-on-FHIR COUNT queries)
        # IMPORTANT: Close old connection pool before query to avoid event loop conflicts
        try:
            await st.session_state.feasibility_service.close()
        except Exception as e:
            logger.warning(f"Failed to close old feasibility service: {e}")

        # Create fresh FeasibilityService with new connection pool
        st.session_state.feasibility_service = FeasibilityService()

        st.write("📊 Calculating feasibility (using SQL-on-FHIR)...")
        feasibility_data = await st.session_state.feasibility_service.execute_feasibility_check(
            query_intent.__dict__ if hasattr(query_intent, "__dict__") else query_intent
        )
        st.write(f"✅ Found approximately {feasibility_data['estimated_cohort']} patients")

        status.update(label="Feasibility analysis complete!", state="complete")

    # Store for later
    st.session_state.pending_feasibility = feasibility_data
    st.session_state.last_query_intent = query_intent

    # Check if this is a count_distinct query
    is_count_distinct = feasibility_data.get("is_count_distinct_query", False)
    # Check if this is a breakdown query
    is_breakdown = feasibility_data.get("is_breakdown_query", False)

    if is_count_distinct:
        # Format count_distinct response
        feasibility_response = format_count_distinct_response(feasibility_data)
    elif is_breakdown:
        # Format breakdown response
        feasibility_response = format_breakdown_response(feasibility_data)
    else:
        # Format and show feasibility response with portal routing
        cohort_size = feasibility_data["estimated_cohort"]
        feasibility_response = f"""
## Feasibility Analysis

**Estimated Cohort Size**: {cohort_size} patients

{"✅ This appears to be a good cohort size for your study." if cohort_size >= 30 else "⚠️ Small cohort size - consider broadening criteria."}

**Next Steps:**
- Type **"proceed"** to submit to the Formal Portal for full data extraction
- Or ask another question to refine your search
"""

    st.session_state.messages.append({"role": "assistant", "content": feasibility_response})

    # Set conversation state to awaiting confirmation
    st.session_state.conversation_state = ConversationState.AWAITING_CONFIRMATION


async def submit_research_request():
    """Submit research request to orchestrator via API"""
    try:
        # Get stored data
        query_intent = st.session_state.last_query_intent
        feasibility_data = st.session_state.pending_feasibility

        # Build structured requirements from feasibility data
        structured_requirements = {
            "study_title": f"Research Notebook Query - {datetime.now().strftime('%Y-%m-%d')}",
            "principal_investigator": "Research Notebook User",
            "inclusion_criteria": (
                getattr(query_intent, "inclusion_criteria", [])
                if hasattr(query_intent, "inclusion_criteria")
                else []
            ),
            "exclusion_criteria": (
                getattr(query_intent, "exclusion_criteria", [])
                if hasattr(query_intent, "exclusion_criteria")
                else []
            ),
            "data_elements": (
                getattr(query_intent, "data_elements", [])
                if hasattr(query_intent, "data_elements")
                else []
            ),
            "time_period": feasibility_data.get("time_period", {}),
            "estimated_cohort_size": feasibility_data.get("estimated_cohort", 0),
            "delivery_format": "CSV",
            "phi_level": "de-identified",
        }

        # Prepare submission
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Submit to research API
            response = await client.post(
                "http://localhost:8000/research/submit",
                json={
                    "researcher_name": "Research Notebook User",
                    "researcher_email": "researcher@hospital.org",
                    "researcher_department": "Clinical Research",
                    "irb_number": "IRB-NOTEBOOK-001",
                    "initial_request": st.session_state.messages[-2][
                        "content"
                    ],  # User's original query
                    "structured_requirements": structured_requirements,  # Pass pre-structured requirements
                },
            )
            response.raise_for_status()
            result = response.json()

            request_id = result.get("request_id")
            st.session_state.pending_request_id = request_id

            # Trigger processing with structured requirements
            process_response = await client.post(
                f"http://localhost:8000/research/process/{request_id}",
                json={
                    "structured_requirements": structured_requirements,
                    "skip_conversation": True,  # Indicate we already have requirements
                },
            )
            process_response.raise_for_status()

            # REMOVED: conversation_state (agent handles this now)

            # Show confirmation message
            confirmation_message = f"""### ✅ Research Request Submitted!

**Request ID:** {request_id}

Your data request has been submitted and is now entering the approval workflow:

1. ✅ Requirements extracted
2. ⏸️ **Awaiting informatician SQL review** (CRITICAL)
3. ⏸️ Data extraction (after approval)
4. ⏸️ Quality assurance
5. ⏸️ Data delivery

**Estimated Time:** 1-24 hours (depending on informatician availability)

💡 **Tip:** Type **'status'** anytime to check progress. I'll notify you when approved!

You can continue using the notebook for other queries while waiting."""

            st.session_state.messages.append({"role": "assistant", "content": confirmation_message})

    except Exception as e:
        error_message = (
            f"❌ **Error submitting request:** {str(e)}\n\nPlease try again or contact support."
        )
        st.session_state.messages.append({"role": "assistant", "content": error_message})


def render_sidebar():
    """Render sidebar"""
    with st.sidebar:
        st.header("🔍 Exploratory Portal")
        st.caption("Fast feasibility checks")

        # Portal info
        st.info(
            "**🚀 Need Full Data Extraction?**\n\nUse the [Formal Portal](http://localhost:8501) for:\n- Complete approval workflow\n- Data extraction & QA\n- Secure delivery"
        )

        # Session info
        st.metric("Messages", len(st.session_state.messages))

        # Pending request
        if st.session_state.pending_request_id:
            st.metric("Active Request", st.session_state.pending_request_id)

        # Quick actions
        st.markdown("---")
        st.markdown("### Quick Actions")

        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.pending_feasibility = None
            st.session_state.pending_request_id = None
            st.session_state.last_query_intent = None
            st.session_state.conversation_state = ConversationState.INITIAL
            st.rerun()

        # Example queries
        st.markdown("### 💡 Example Queries")
        examples = [
            "How many patients are available?",
            "Patients with diabetes and HbA1c > 8%",
            "Female patients with hypertension under 65",
        ]

        for example in examples:
            if st.button(example, key=f"ex_{example[:20]}", use_container_width=True):
                st.session_state.example_query = example
                st.rerun()

        # Portal capabilities
        st.markdown("---")
        st.caption("**Exploratory Portal:**")
        st.caption("✅ Instant cohort counts")
        st.caption("✅ Natural language queries")
        st.caption("✅ SQL-on-FHIR execution")
        st.caption("")
        st.caption("**Formal Portal:**")
        st.caption("🔐 Full approval workflow")
        st.caption("📦 Data extraction & delivery")


def main():
    """Main application"""
    # Initialize
    initialize_session_state()

    # Header
    st.title("🔍 ResearchFlow - Exploratory Portal")
    st.caption(
        "**Fast Feasibility Checks** • Ask questions, get instant cohort counts • For full data extraction, use the Formal Portal"
    )

    # Sidebar
    render_sidebar()

    # Display chat messages
    for idx, message in enumerate(st.session_state.messages):
        role = message["role"]
        content = message["content"]

        if role == "user":
            st.markdown(
                f"""
<div class="chat-message user-message">
    <strong>👤 You:</strong><br/>
    {content}
</div>
            """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""
<div class="chat-message assistant-message">
    <strong>🤖 ResearchFlow:</strong><br/>
            """,
                unsafe_allow_html=True,
            )
            st.markdown(content)

            # Display SQL expander INSIDE the chat bubble if this is the last message and we have feasibility data
            # IMPORTANT: This shows the ACTUAL SQL executed by the backend (JoinQueryBuilder)
            # - Uses sqlonfhir schema (e.g., FROM sqlonfhir.patient_demographics)
            # - Can be copy-pasted and run directly in database tool
            # - Never shows LLM-generated "friendly" SQL
            if (
                idx == len(st.session_state.messages) - 1
                and st.session_state.pending_feasibility
                and st.session_state.pending_feasibility.get("generated_sql")
            ):

                feasibility_data = st.session_state.pending_feasibility

                with st.expander("🔍 View Actual SQL Query (Backend)", expanded=False):
                    st.code(feasibility_data["generated_sql"], language="sql")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric(
                            "Execution Time",
                            f"{feasibility_data.get('execution_time_ms', 0):.1f} ms",
                        )
                    with col2:
                        st.metric(
                            "Query Type",
                            "JOIN" if feasibility_data.get("used_join_query") else "Single View",
                        )
                    with col3:
                        st.metric("Result Count", feasibility_data["estimated_cohort"])

                    if feasibility_data.get("filter_summary"):
                        st.info(f"**Filters Applied:** {feasibility_data['filter_summary']}")

            st.markdown("</div>", unsafe_allow_html=True)

    # Chat input
    user_input = st.chat_input("Ask about patient data, check status, or get help...")

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
