"""
ResearchFlow Researcher Portal

Streamlit interface for researchers to submit and track data requests.
"""

import streamlit as st
import asyncio
from datetime import datetime
import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.orchestrator import ResearchRequestOrchestrator
from app.agents import (
    RequirementsAgent,
    PhenotypeValidationAgent,
    CalendarAgent,
    DataExtractionAgent,
    QualityAssuranceAgent,
    DeliveryAgent
)


def initialize_orchestrator():
    """Initialize orchestrator with all agents"""
    if 'orchestrator' not in st.session_state:
        orchestrator = ResearchRequestOrchestrator()

        # Get HAPI FHIR database URL from environment
        hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")

        # Register all agents (phenotype agent needs HAPI database for ViewDefinitions)
        orchestrator.register_agent('requirements_agent', RequirementsAgent())
        orchestrator.register_agent('phenotype_agent', PhenotypeValidationAgent(database_url=hapi_db_url))
        orchestrator.register_agent('calendar_agent', CalendarAgent())
        orchestrator.register_agent('extraction_agent', DataExtractionAgent())
        orchestrator.register_agent('qa_agent', QualityAssuranceAgent())
        orchestrator.register_agent('delivery_agent', DeliveryAgent())

        st.session_state.orchestrator = orchestrator


def main():
    """Main researcher portal application"""
    st.set_page_config(
        page_title="ResearchFlow - Data Request Portal",
        page_icon="🔬",
        layout="wide"
    )

    # Initialize orchestrator
    initialize_orchestrator()

    # Header
    st.title("🔬 ResearchFlow - Clinical Data Request Platform")
    st.caption("AI-powered research data requests | From request to data in hours")

    # Sidebar - My Requests
    with st.sidebar:
        st.header("📊 My Requests")

        if 'user_requests' not in st.session_state:
            st.session_state.user_requests = []

        if st.session_state.user_requests:
            for req_id in st.session_state.user_requests:
                status = asyncio.run(st.session_state.orchestrator.get_request_status(req_id))
                if status:
                    with st.expander(f"Request #{req_id[:8]}..."):
                        st.write(f"**Status:** {status['current_state']}")
                        st.write(f"**Started:** {status['started_at'][:19]}")

                        if st.button("View Details", key=f"view_{req_id}"):
                            st.session_state.selected_request = req_id
        else:
            st.info("No requests yet. Submit a new request below!")

    # Main content area
    tab1, tab2 = st.tabs(["🆕 New Request", "📋 Request Details"])

    with tab1:
        show_new_request_form()

    with tab2:
        show_request_details()


def show_new_request_form():
    """Display new request submission form"""
    st.header("Submit New Data Request")

    st.markdown("""
    Describe your research data needs in natural language. Our AI assistant will help you
    define your requirements through a conversational interface.
    """)

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
            placeholder="Example: I need clinical notes and lab results for heart failure patients admitted in 2024 who had a prior diabetes diagnosis. De-identified data is fine.",
            height=150
        )

        submit = st.form_submit_button("Submit Request", type="primary")

        if submit:
            if not all([name, email, irb_number, request_text]):
                st.error("Please fill in all required fields (*)")
            else:
                # Submit request
                with st.spinner("Submitting your request..."):
                    try:
                        researcher_info = {
                            "name": name,
                            "email": email,
                            "department": department,
                            "irb_number": irb_number
                        }

                        # Create async event loop to submit request
                        request_id = asyncio.run(
                            st.session_state.orchestrator.process_new_request(
                                researcher_request=request_text,
                                researcher_info=researcher_info
                            )
                        )

                        # Add to session state
                        if 'user_requests' not in st.session_state:
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
    if 'selected_request' not in st.session_state:
        st.info("Select a request from the sidebar to view details")
        return

    request_id = st.session_state.selected_request
    status = asyncio.run(st.session_state.orchestrator.get_request_status(request_id))

    if not status:
        st.error(f"Request not found: {request_id}")
        return

    # Request header
    st.header(f"Request: {request_id}")

    # Status overview
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Status", status['current_state'])
    with col2:
        st.metric("Current Agent", status.get('current_agent', 'None'))
    with col3:
        started = datetime.fromisoformat(status['started_at'])
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
        "delivered"
    ]

    current_idx = -1
    if status['current_state'] in workflow_states:
        current_idx = workflow_states.index(status['current_state'])

    progress = (current_idx + 1) / len(workflow_states) if current_idx >= 0 else 0
    st.progress(progress)

    # State history
    st.subheader("📊 Agent Activity")

    if status.get('agents_involved'):
        for activity in reversed(status['agents_involved']):
            agent_name = activity['agent'].replace('_', ' ').title()
            task_name = activity['task'].replace('_', ' ').title()
            timestamp = activity['timestamp'][:19]

            st.markdown(f"**{timestamp}** - {agent_name}: {task_name}")
    else:
        st.info("No agent activity yet")

    # Researcher info
    st.subheader("👤 Researcher Information")
    researcher = status.get('researcher_info', {})
    st.write(f"**Name:** {researcher.get('name', 'N/A')}")
    st.write(f"**Email:** {researcher.get('email', 'N/A')}")
    st.write(f"**IRB:** {researcher.get('irb_number', 'N/A')}")


if __name__ == "__main__":
    main()
