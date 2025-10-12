"""
ResearchFlow Admin Dashboard

Streamlit interface for administrators to monitor system and review escalations.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import asyncio
import time
import sys
import os
import requests
import json
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

        # Register all agents
        orchestrator.register_agent('requirements_agent', RequirementsAgent())
        orchestrator.register_agent('phenotype_agent', PhenotypeValidationAgent())
        orchestrator.register_agent('calendar_agent', CalendarAgent())
        orchestrator.register_agent('extraction_agent', DataExtractionAgent())
        orchestrator.register_agent('qa_agent', QualityAssuranceAgent())
        orchestrator.register_agent('delivery_agent', DeliveryAgent())

        st.session_state.orchestrator = orchestrator


def main():
    """Main admin dashboard application"""
    st.set_page_config(
        page_title="ResearchFlow - Admin Dashboard",
        page_icon="⚙️",
        layout="wide"
    )

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
            disabled=not auto_refresh
        )

    with col3:
        if st.button("🔄 Refresh Now", key="manual_refresh"):
            st.rerun()

    with col4:
        if 'last_refresh' in st.session_state:
            st.caption(f"Last updated: {st.session_state.last_refresh.strftime('%H:%M:%S')}")

    # Update last refresh time
    st.session_state.last_refresh = datetime.now()

    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Overview",
        "🤖 Agent Metrics",
        "✋ Pending Approvals",
        "🚨 Escalations",
        "📈 Analytics"
    ])

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
    requests = asyncio.run(st.session_state.orchestrator.get_all_active_requests())

    # Metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Requests", len(requests))

    with col2:
        in_progress = len([r for r in requests if r['current_state'] not in ['delivered', 'complete', 'failed']])
        st.metric("In Progress", in_progress)

    with col3:
        completed = len([r for r in requests if r['current_state'] in ['delivered', 'complete']])
        st.metric("Completed", completed)

    with col4:
        failed = len([r for r in requests if r['current_state'] == 'failed'])
        st.metric("Failed/Escalated", failed, delta=-failed if failed > 0 else None)

    # Recent requests
    st.subheader("📋 Recent Requests")

    if requests:
        df_data = []
        for req in requests[:10]:  # Show last 10
            df_data.append({
                "Request ID": req['request_id'][:16] + "...",
                "Researcher": req['researcher_info'].get('name', 'N/A'),
                "Status": req['current_state'],
                "Current Agent": req.get('current_agent', 'None'),
                "Started": req['started_at'][:19]
            })

        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No requests yet")


def show_agent_metrics():
    """Display agent performance metrics"""
    st.header("🤖 Agent Performance Metrics")

    # Get metrics for all agents
    all_metrics = st.session_state.orchestrator.get_agent_metrics()

    if not all_metrics:
        st.info("No agent metrics available yet")
        return

    # Create metrics table
    metrics_data = []
    for agent_id, metrics in all_metrics.items():
        agent_name = agent_id.replace('_', ' ').title()
        metrics_data.append({
            "Agent": agent_name,
            "State": metrics['state'],
            "Total Tasks": metrics['total_tasks'],
            "Successful": metrics['successful_tasks'],
            "Failed": metrics['failed_tasks'],
            "Success Rate": f"{metrics['success_rate']:.1%}",
            "Avg Duration (s)": f"{metrics['avg_duration_seconds']:.1f}"
        })

    df = pd.DataFrame(metrics_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Agent status indicators
    st.subheader("Agent Status")

    cols = st.columns(3)
    for idx, (agent_id, metrics) in enumerate(all_metrics.items()):
        with cols[idx % 3]:
            agent_name = agent_id.replace('_', ' ').title()
            status = metrics['state']
            status_emoji = "🟢" if status == "idle" else "🔵" if status == "working" else "🔴"

            st.metric(
                f"{status_emoji} {agent_name}",
                status,
                f"{metrics['total_tasks']} tasks"
            )


def show_pending_approvals():
    """Display pending approvals requiring human review"""
    st.header("✋ Pending Approvals - Human-in-Loop Gates")

    # API base URL
    API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

    # Filter by approval type
    col1, col2, col3 = st.columns([2, 2, 6])

    with col1:
        approval_type_filter = st.selectbox(
            "Filter by Type",
            ["All", "Requirements", "Phenotype SQL", "Extraction", "QA", "Scope Change"],
            key="approval_type_filter"
        )

    with col2:
        reviewer_email = st.text_input(
            "Your Email",
            placeholder="informatician@hospital.org",
            key="reviewer_email"
        )

    # Fetch pending approvals
    try:
        # Map UI selections to API values
        type_map = {
            "All": None,
            "Requirements": "requirements",
            "Phenotype SQL": "phenotype_sql",
            "Extraction": "extraction",
            "QA": "qa",
            "Scope Change": "scope_change"
        }

        approval_type_param = type_map[approval_type_filter]
        params = {"approval_type": approval_type_param} if approval_type_param else {}

        response = requests.get(f"{API_BASE}/approvals/pending", params=params, timeout=5)

        if response.status_code == 200:
            data = response.json()
            approvals = data.get('approvals', [])

            # Metrics
            st.subheader("📊 Approval Queue Metrics")

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("Total Pending", data.get('count', 0))

            with col2:
                sql_approvals = len([a for a in approvals if a.get('approval_type') == 'phenotype_sql'])
                st.metric("🔴 SQL Reviews", sql_approvals, help="CRITICAL - SQL must be approved before execution")

            with col3:
                req_approvals = len([a for a in approvals if a.get('approval_type') == 'requirements'])
                st.metric("Requirements", req_approvals)

            with col4:
                scope_approvals = len([a for a in approvals if a.get('approval_type') == 'scope_change'])
                st.metric("Scope Changes", scope_approvals)

            # Display approvals
            st.subheader("📋 Pending Approvals")

            if not approvals:
                st.success("✅ No pending approvals - all reviews complete!")
            else:
                for approval in approvals:
                    display_approval_card(approval, reviewer_email, API_BASE)

        else:
            st.error(f"Failed to fetch approvals: {response.status_code}")

    except requests.exceptions.ConnectionError:
        st.warning("⚠️ Cannot connect to API server. Please ensure the API is running on port 8000.")
        st.info("Run: `make run` or `uvicorn app.main:app --reload --port 8000`")

    except Exception as e:
        st.error(f"Error fetching approvals: {str(e)}")


def display_approval_card(approval, reviewer_email, api_base):
    """Display a single approval card with all details and action buttons"""
    approval_id = approval['id']
    approval_type = approval['approval_type']
    request_id = approval['request_id']
    submitted_at = approval['submitted_at']
    submitted_by = approval.get('submitted_by', 'Unknown')
    timeout_at = approval.get('timeout_at')
    approval_data = approval.get('approval_data', {})

    # Determine urgency based on timeout
    urgency = "🟢 Normal"
    if timeout_at:
        timeout_dt = datetime.fromisoformat(timeout_at.replace('Z', '+00:00'))
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
        "scope_change": "🔄"
    }

    type_label_map = {
        "requirements": "Requirements Review",
        "phenotype_sql": "SQL REVIEW (CRITICAL)",
        "extraction": "Extraction Approval",
        "qa": "QA Review",
        "scope_change": "Scope Change"
    }

    emoji = type_emoji_map.get(approval_type, "📋")
    label = type_label_map.get(approval_type, approval_type.title())

    # Create expander with urgency indicator
    with st.expander(f"{emoji} {label} - {request_id[:20]}... | {urgency}", expanded=(approval_type == "phenotype_sql")):
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
            if st.button("✅ Approve", key=f"approve_{approval_id}", type="primary", use_container_width=True):
                if not reviewer_email:
                    st.error("Please enter your email address")
                else:
                    handle_approval_response(approval_id, "approve", reviewer_email, "", {}, api_base)

        with col2:
            if st.button("✏️ Modify & Approve", key=f"modify_{approval_id}", use_container_width=True):
                st.session_state[f'show_modify_{approval_id}'] = True

        with col3:
            if st.button("❌ Reject", key=f"reject_{approval_id}", use_container_width=True):
                st.session_state[f'show_reject_{approval_id}'] = True

        # Modification interface
        if st.session_state.get(f'show_modify_{approval_id}', False):
            st.subheader("Approve with Modifications")
            notes = st.text_area("Notes", placeholder="Explain your modifications...", key=f"modify_notes_{approval_id}")

            if approval_type == "phenotype_sql":
                modified_sql = st.text_area(
                    "Modified SQL Query",
                    value=approval_data.get('sql_query', ''),
                    height=200,
                    key=f"modified_sql_{approval_id}"
                )
                modifications = {"sql_query": modified_sql}
            else:
                modifications = {}

            if st.button("Submit Modifications", key=f"submit_modify_{approval_id}"):
                if not reviewer_email:
                    st.error("Please enter your email address")
                else:
                    handle_approval_response(approval_id, "modify", reviewer_email, notes, modifications, api_base)
                    st.session_state[f'show_modify_{approval_id}'] = False

        # Rejection interface
        if st.session_state.get(f'show_reject_{approval_id}', False):
            st.subheader("Reject Approval")
            reject_reason = st.text_area(
                "Reason for Rejection",
                placeholder="Explain why this is being rejected and what needs to be fixed...",
                key=f"reject_reason_{approval_id}"
            )

            if st.button("Confirm Rejection", key=f"confirm_reject_{approval_id}", type="secondary"):
                if not reviewer_email:
                    st.error("Please enter your email address")
                elif not reject_reason:
                    st.error("Please provide a reason for rejection")
                else:
                    handle_approval_response(approval_id, "reject", reviewer_email, reject_reason, {}, api_base)
                    st.session_state[f'show_reject_{approval_id}'] = False


def display_sql_approval(data):
    """Display SQL approval details with syntax highlighting"""
    st.subheader("🔴 CRITICAL: SQL Query Review")

    st.warning("""
    **IMPORTANT:** This SQL query will execute against the production FHIR database if approved.
    Please verify:
    - SQL syntax is correct
    - Date filters are appropriate
    - Cohort size is reasonable
    - No sensitive fields are exposed
    - Joins and selections are accurate
    """)

    # SQL Query
    sql_query = data.get('sql_query', 'N/A')
    st.code(sql_query, language='sql')

    # Metrics
    col1, col2, col3 = st.columns(3)

    with col1:
        cohort = data.get('estimated_cohort', 'Unknown')
        st.metric("Estimated Cohort", cohort)

    with col2:
        feasibility = data.get('feasibility_score', 0)
        st.metric("Feasibility Score", f"{feasibility:.2f}")

    with col3:
        availability = data.get('data_availability', {}).get('overall_availability', 0)
        st.metric("Data Availability", f"{availability:.1%}")

    # Warnings
    warnings = data.get('warnings', [])
    if warnings:
        st.warning("⚠️ **Warnings:**")
        for warning in warnings:
            st.write(f"- {warning.get('message', warning)}")

    # Recommendations
    recommendations = data.get('recommendations', [])
    if recommendations:
        st.info("💡 **Recommendations:**")
        for rec in recommendations:
            st.write(f"- {rec}")


def display_requirements_approval(data):
    """Display requirements approval details"""
    st.subheader("📄 Requirements Review")

    structured_reqs = data.get('structured_requirements', {})
    completeness = data.get('completeness_score', 0)

    # Completeness score
    st.metric("Completeness Score", f"{completeness:.1%}")

    # Study details
    if 'study_title' in structured_reqs:
        st.write(f"**Study Title:** {structured_reqs['study_title']}")

    # Inclusion criteria
    inclusion = structured_reqs.get('inclusion_criteria', [])
    if inclusion:
        st.write("**Inclusion Criteria:**")
        for criterion in inclusion:
            st.write(f"- {criterion}")

    # Exclusion criteria
    exclusion = structured_reqs.get('exclusion_criteria', [])
    if exclusion:
        st.write("**Exclusion Criteria:**")
        for criterion in exclusion:
            st.write(f"- {criterion}")

    # Data elements
    elements = structured_reqs.get('data_elements', [])
    if elements:
        st.write(f"**Data Elements:** {', '.join(elements)}")

    # Full requirements
    with st.expander("View Full Requirements"):
        st.json(structured_reqs)


def display_scope_change_approval(data):
    """Display scope change approval with impact analysis"""
    st.subheader("🔄 Scope Change Request")

    requested_changes = data.get('requested_changes', {})
    reason = data.get('reason', 'N/A')
    impact = data.get('impact_analysis', {})

    # Reason
    st.write(f"**Reason:** {reason}")

    # Requested changes
    st.write("**Requested Changes:**")
    st.json(requested_changes)

    st.divider()

    # Impact analysis
    st.subheader("📊 Impact Analysis")

    severity = impact.get('severity', 'unknown')
    severity_color = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(severity, "⚪")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Severity", f"{severity_color} {severity.title()}")

    with col2:
        requires_rework = impact.get('requires_rework', False)
        st.metric("Requires Rework", "Yes" if requires_rework else "No")

    with col3:
        delay = impact.get('estimated_delay_hours', 0)
        st.metric("Estimated Delay", f"{delay}h")

    # Restart point
    if impact.get('restart_from_state'):
        st.warning(f"⚠️ **Workflow will restart from:** `{impact['restart_from_state']}`")

    # Affected components
    affected = impact.get('affected_components', [])
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


def handle_approval_response(approval_id, decision, reviewer, notes, modifications, api_base):
    """Handle approval response (approve/reject/modify)"""
    try:
        payload = {
            "decision": decision,
            "reviewer": reviewer,
            "notes": notes
        }

        if modifications:
            payload["modifications"] = modifications

        response = requests.post(
            f"{api_base}/approvals/{approval_id}/respond",
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            result = response.json()

            if decision == "approve":
                st.success(f"✅ Approval {approval_id} approved! Workflow will continue automatically.")
            elif decision == "reject":
                st.error(f"❌ Approval {approval_id} rejected. Request will return to originating agent.")
            elif decision == "modify":
                st.success(f"✏️ Approval {approval_id} approved with modifications. Workflow will continue with your changes.")

            # Trigger refresh after 2 seconds
            time.sleep(2)
            st.rerun()
        else:
            st.error(f"Failed to process approval: {response.status_code} - {response.text}")

    except Exception as e:
        st.error(f"Error processing approval: {str(e)}")


def show_escalations():
    """Display escalations requiring human review"""
    st.header("🚨 Escalations & Human Review Queue")

    st.info("""
    **Note:** Escalations will appear here when:
    - Agents encounter errors after max retries
    - Data quality checks fail critically
    - Requests are not feasible
    - Complex decisions require human judgment
    """)

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
    dates = pd.date_range(start=datetime.now() - timedelta(days=30), end=datetime.now(), freq='D')
    volume_data = pd.DataFrame({
        'Date': dates,
        'Submitted': [i % 5 + 2 for i in range(len(dates))],
        'Completed': [i % 4 + 1 for i in range(len(dates))]
    })

    st.line_chart(volume_data.set_index('Date'))

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

    element_data = pd.DataFrame({
        'Element': ['Clinical Notes', 'Lab Results', 'Medications', 'Diagnoses', 'Procedures'],
        'Requests': [45, 38, 32, 28, 15]
    })

    st.bar_chart(element_data.set_index('Element'))


if __name__ == "__main__":
    main()
