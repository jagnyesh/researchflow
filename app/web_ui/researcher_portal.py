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
from datetime import datetime
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
    DeliveryAgent,
)
from app.database import get_engine


def run_async(coroutine):
    """
    Run async code in Streamlit's persistent event loop.

    Uses the loop set up at module import time to ensure all
    database operations use the same loop.
    """
    return _streamlit_loop.run_until_complete(coroutine)


def initialize_orchestrator():
    """Initialize orchestrator with all agents"""
    if "orchestrator" not in st.session_state:
        # Ensure database engine is initialized for current event loop
        # This prevents "Queue is bound to a different event loop" errors
        get_engine()
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

        if "user_requests" not in st.session_state:
            st.session_state.user_requests = []

        if st.session_state.user_requests:
            for req_id in st.session_state.user_requests:
                status = run_async(st.session_state.orchestrator.get_request_status(req_id))
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


if __name__ == "__main__":
    main()
