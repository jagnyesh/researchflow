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

import streamlit as st
import asyncio
import sys
import os
import httpx
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load environment variables from project root (explicit path)
# Get project root: /Users/.../FHIR_PROJECT
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
dotenv_path = os.path.join(project_root, '.env')

# Load .env file
load_dotenv(dotenv_path)

# Verify critical environment variables are loaded
anthropic_key = os.getenv('ANTHROPIC_API_KEY')
if anthropic_key:
    print(f"✓ Loaded ANTHROPIC_API_KEY from: {dotenv_path} (key starts with: {anthropic_key[:20]}...)")
else:
    print(f"⚠️  WARNING: ANTHROPIC_API_KEY not found! Checked: {dotenv_path}")
    print(f"   Query interpretation will fall back to dummy mode (inaccurate results)")

# Add parent directory to path
sys.path.insert(0, project_root)

from app.services.conversation_manager import ConversationManager, UserIntent, ConversationState
from app.services.feasibility_service import FeasibilityService
from app.services.query_interpreter import QueryInterpreter
from app.components.approval_tracker import ApprovalTracker

# Page config
st.set_page_config(
    page_title="ResearchFlow - Interactive Research Assistant",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
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
""", unsafe_allow_html=True)


def initialize_session_state():
    """Initialize session state variables"""
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    if 'conversation_manager' not in st.session_state:
        st.session_state.conversation_manager = ConversationManager()

    if 'feasibility_service' not in st.session_state:
        st.session_state.feasibility_service = FeasibilityService()

    if 'query_interpreter' not in st.session_state:
        st.session_state.query_interpreter = QueryInterpreter()

    if 'approval_tracker' not in st.session_state:
        st.session_state.approval_tracker = ApprovalTracker()

    if 'conversation_state' not in st.session_state:
        st.session_state.conversation_state = ConversationState.INITIAL

    if 'pending_feasibility' not in st.session_state:
        st.session_state.pending_feasibility = None

    if 'pending_request_id' not in st.session_state:
        st.session_state.pending_request_id = None

    if 'last_query_intent' not in st.session_state:
        st.session_state.last_query_intent = None


async def handle_user_input(user_input: str):
    """
    Handle user input with conversational flow

    Workflow:
    1. Detect intent (greeting/query/confirmation/status)
    2. Route to appropriate handler
    3. Update conversation state
    """
    # Detect intent
    intent = st.session_state.conversation_manager.detect_intent(user_input)

    # Handle based on intent
    if intent == UserIntent.GREETING:
        await handle_greeting()

    elif intent == UserIntent.HELP:
        await handle_help()

    elif intent == UserIntent.STATUS_CHECK:
        await handle_status_check()

    elif intent == UserIntent.CONFIRMATION:
        await handle_confirmation(user_input)

    elif intent == UserIntent.QUERY:
        await handle_query(user_input)

    else:
        # Unknown intent
        response = "I'm not sure I understand. Type **'help'** to see what I can do."
        st.session_state.messages.append({"role": "assistant", "content": response})


async def handle_greeting():
    """Handle greeting intent"""
    introduction = st.session_state.conversation_manager.get_introduction()
    st.session_state.messages.append({"role": "assistant", "content": introduction})
    st.session_state.conversation_state = ConversationState.INITIAL


async def handle_help():
    """Handle help intent"""
    help_message = st.session_state.conversation_manager.get_help_message()
    st.session_state.messages.append({"role": "assistant", "content": help_message})


async def handle_status_check():
    """Handle status check intent"""
    if st.session_state.pending_request_id:
        request_id = st.session_state.pending_request_id

        # Get status from API
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(f"http://localhost:8000/research/{request_id}")
                response.raise_for_status()
                status_data = response.json()

                # Format status response
                status_message = st.session_state.conversation_manager.format_approval_status(
                    request_id=request_id,
                    current_state=status_data.get("current_state", "unknown")
                )
                st.session_state.messages.append({"role": "assistant", "content": status_message})

            except Exception as e:
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"Error retrieving status: {str(e)}"
                })
    else:
        st.session_state.messages.append({
            "role": "assistant",
            "content": "You don't have any active requests. Ask a research question to get started!"
        })


async def handle_confirmation(user_input: str):
    """Handle confirmation/rejection"""
    is_confirmation = st.session_state.conversation_manager.is_confirmation(user_input)
    is_rejection = st.session_state.conversation_manager.is_rejection(user_input)

    if st.session_state.conversation_state == ConversationState.AWAITING_CONFIRMATION:
        if is_confirmation:
            # User confirmed - submit to research API
            await submit_research_request()
        elif is_rejection:
            # User rejected - clear pending data
            st.session_state.pending_feasibility = None
            st.session_state.last_query_intent = None
            st.session_state.conversation_state = ConversationState.INITIAL
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Understood. Feel free to refine your criteria and ask again!"
            })
        else:
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Please answer **'yes'** to proceed or **'no'** to cancel."
            })
    else:
        # Not awaiting confirmation
        st.session_state.messages.append({
            "role": "assistant",
            "content": "I'm not waiting for a confirmation. Ask a research question to get started!"
        })


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
        st.write("📊 Calculating feasibility (using SQL-on-FHIR)...")
        feasibility_data = await st.session_state.feasibility_service.execute_feasibility_check(
            query_intent.__dict__ if hasattr(query_intent, '__dict__') else query_intent
        )
        st.write(f"✅ Found approximately {feasibility_data['estimated_cohort']} patients")

        status.update(label="Feasibility analysis complete!", state="complete")

    # Store for later
    st.session_state.pending_feasibility = feasibility_data
    st.session_state.last_query_intent = query_intent
    st.session_state.conversation_state = ConversationState.AWAITING_CONFIRMATION

    # Format and show feasibility response
    feasibility_response = st.session_state.conversation_manager.format_feasibility_response(
        cohort_size=feasibility_data['estimated_cohort'],
        feasibility_data=feasibility_data
    )

    st.session_state.messages.append({
        "role": "assistant",
        "content": feasibility_response
    })

    # Display SQL visibility (for testing/debugging)
    if feasibility_data.get('generated_sql'):
        with st.expander("🔍 View Generated SQL Query", expanded=False):
            st.code(feasibility_data['generated_sql'], language='sql')

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Execution Time", f"{feasibility_data.get('execution_time_ms', 0):.1f} ms")
            with col2:
                st.metric("Query Type", "JOIN" if feasibility_data.get('used_join_query') else "Single View")
            with col3:
                st.metric("Result Count", feasibility_data['estimated_cohort'])

            if feasibility_data.get('filter_summary'):
                st.info(f"**Filters Applied:** {feasibility_data['filter_summary']}")

            # Copy to clipboard button
            if st.button("📋 Copy SQL", key="copy_sql"):
                st.code(feasibility_data['generated_sql'], language='sql')
                st.success("SQL copied to clipboard!")


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
            "inclusion_criteria": getattr(query_intent, 'inclusion_criteria', []) if hasattr(query_intent, 'inclusion_criteria') else [],
            "exclusion_criteria": getattr(query_intent, 'exclusion_criteria', []) if hasattr(query_intent, 'exclusion_criteria') else [],
            "data_elements": getattr(query_intent, 'data_elements', []) if hasattr(query_intent, 'data_elements') else [],
            "time_period": feasibility_data.get('time_period', {}),
            "estimated_cohort_size": feasibility_data.get('estimated_cohort', 0),
            "delivery_format": "CSV",
            "phi_level": "de-identified"
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
                    "initial_request": st.session_state.messages[-2]["content"],  # User's original query
                    "structured_requirements": structured_requirements  # Pass pre-structured requirements
                }
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
                    "skip_conversation": True  # Indicate we already have requirements
                }
            )
            process_response.raise_for_status()

            # Update conversation state
            st.session_state.conversation_state = ConversationState.AWAITING_APPROVAL

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

            st.session_state.messages.append({
                "role": "assistant",
                "content": confirmation_message
            })

    except Exception as e:
        error_message = f"❌ **Error submitting request:** {str(e)}\n\nPlease try again or contact support."
        st.session_state.messages.append({
            "role": "assistant",
            "content": error_message
        })


def render_sidebar():
    """Render sidebar"""
    with st.sidebar:
        st.header("🤖 ResearchFlow")

        # Session info
        st.metric("Messages", len(st.session_state.messages))

        # Conversation state
        state = st.session_state.conversation_state.value
        st.metric("Conversation State", state.replace('_', ' ').title())

        # Pending request
        if st.session_state.pending_request_id:
            st.metric("Active Request", st.session_state.pending_request_id)

            # Show approval tracking
            if st.button("🔍 Check Request Status", use_container_width=True):
                asyncio.run(handle_status_check())
                st.rerun()

        # Quick actions
        st.markdown("---")
        st.markdown("### Quick Actions")

        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.conversation_state = ConversationState.INITIAL
            st.session_state.pending_feasibility = None
            st.session_state.pending_request_id = None
            st.session_state.last_query_intent = None
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

        # System info
        st.markdown("---")
        st.caption("**Two-Stage Workflow:**")
        st.caption("1️⃣ Feasibility (SQL-on-FHIR)")
        st.caption("2️⃣ Extraction (Orchestrator)")


def main():
    """Main application"""
    # Initialize
    initialize_session_state()

    # Header
    st.title("🤖 ResearchFlow - AI Research Assistant")
    st.caption("Ask questions naturally, get approved data extractions")

    # Sidebar
    render_sidebar()

    # Display chat messages
    for message in st.session_state.messages:
        role = message["role"]
        content = message["content"]

        if role == "user":
            st.markdown(f"""
<div class="chat-message user-message">
    <strong>👤 You:</strong><br/>
    {content}
</div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
<div class="chat-message assistant-message">
    <strong>🤖 ResearchFlow:</strong><br/>
            """, unsafe_allow_html=True)
            st.markdown(content)
            st.markdown("</div>", unsafe_allow_html=True)

    # Chat input
    user_input = st.chat_input("Ask about patient data, check status, or get help...")

    # Handle example query from sidebar
    if 'example_query' in st.session_state:
        user_input = st.session_state.example_query
        del st.session_state.example_query

    # Process user input
    if user_input:
        # Add user message
        st.session_state.messages.append({"role": "user", "content": user_input})

        # Handle input
        asyncio.run(handle_user_input(user_input))

        # Rerun to show new messages
        st.rerun()


if __name__ == "__main__":
    main()
