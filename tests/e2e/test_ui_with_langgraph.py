"""
End-to-End UI Tests with LangGraph

Tests the complete user journey through the Streamlit UIs using LangGraph orchestrator.
Since we can't run Streamlit in pytest, these tests simulate UI workflows by calling
the same facade methods that the UIs would use.

Test Scenarios:
1. Researcher submits request via portal → tracks status → views results
2. Admin reviews request in dashboard → approves → workflow continues
3. Complete user journey from researcher submission to data delivery
"""

import pytest
import asyncio
import os
from typing import Dict, Any

from app.langchain_orchestrator.request_facade import LangGraphRequestFacade
from app.database import get_db_session, ResearchRequest, Approval
from sqlalchemy import select


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_researcher_info() -> Dict[str, Any]:
    """Researcher info from portal form"""
    return {
        "name": "Dr. Jane Smith",
        "email": "jsmith@hospital.edu",
        "department": "Cardiology",
        "irb_number": "IRB-2025-001",
        "structured_requirements": {
            "inclusion_criteria": ["Age >= 18", "Diagnosed with diabetes"],
            "exclusion_criteria": ["Pregnant"],
            "data_elements": ["Demographics", "Lab Results"],
            "time_period": {"start": "2024-01-01", "end": "2024-12-31"},
            "phi_level": "de-identified",
        },
    }


# ============================================================================
# Test: Researcher Portal Workflow (LangGraph)
# ============================================================================


@pytest.mark.asyncio
async def test_researcher_portal_submit_and_track_with_langgraph(sample_researcher_info):
    """
    Simulate researcher portal workflow with LangGraph:
    1. Researcher fills out form
    2. Submits request
    3. Tracks request status
    4. Views request details
    """
    # Initialize facade (simulating USE_LANGGRAPH_WORKFLOW=true)
    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)

    # Step 1: Researcher submits request from portal form
    request_id = await facade.process_new_request(
        researcher_request="I need diabetes patient data for 2024 cohort study",
        researcher_info=sample_researcher_info,
    )

    # Verify request created
    assert request_id is not None
    assert request_id.startswith("REQ-")

    # Step 2: Researcher checks status (sidebar in portal)
    await asyncio.sleep(1.0)
    status = await facade.get_request_status(request_id)

    assert status is not None
    assert status["request_id"] == request_id
    assert status["current_state"] in [
        "new_request",
        "requirements_gathering",
        "requirements_approval",
        "feasibility_validation",
    ]

    # Step 3: Researcher views details (details tab)
    assert status["researcher_info"]["name"] == "Dr. Jane Smith"
    assert status["researcher_info"]["email"] == "jsmith@hospital.edu"

    # Step 4: Researcher sees state history
    assert "state_history" in status
    assert len(status["state_history"]) > 0

    await facade.close()


# ============================================================================
# Test: Admin Dashboard Workflow (LangGraph)
# ============================================================================


@pytest.mark.asyncio
async def test_admin_dashboard_review_and_approve_with_langgraph(sample_researcher_info):
    """
    Simulate admin dashboard workflow with LangGraph:
    1. Admin views all active requests
    2. Reviews specific request details
    3. Approves requirements
    4. Workflow continues automatically
    """
    # Initialize facade (simulating USE_LANGGRAPH_WORKFLOW=true)
    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)

    # Researcher submits request
    request_id = await facade.process_new_request(
        researcher_request="Study request", researcher_info=sample_researcher_info
    )

    # Step 1: Admin views all active requests in dashboard
    await asyncio.sleep(1.0)
    active_requests = await facade.get_all_active_requests()

    assert len(active_requests) > 0
    request_ids = [req["request_id"] for req in active_requests]
    assert request_id in request_ids

    # Step 2: Admin clicks on request to view details
    status = await facade.get_request_status(request_id)
    assert status is not None

    # Step 3: Admin approves request (if approval exists)
    await asyncio.sleep(2.0)

    async with get_db_session() as session:
        result = await session.execute(select(Approval).where(Approval.request_id == request_id))
        approval = result.scalar_one_or_none()

        if approval and approval.status == "pending":
            # Admin approves in dashboard
            await facade.process_approval_response(
                approval_id=approval.id,
                reviewer="admin@hospital.edu",
                decision="approve",
                notes="Approved by admin",
            )

            # Step 4: Verify workflow continues
            await asyncio.sleep(1.0)
            updated_status = await facade.get_request_status(request_id)

            # Workflow should have progressed
            assert updated_status["current_state"] != "requirements_approval" or approval is None

    await facade.close()


# ============================================================================
# Test: Complete User Journey
# ============================================================================


@pytest.mark.asyncio
async def test_complete_user_journey_researcher_to_delivery(sample_researcher_info):
    """
    Test complete end-to-end journey:
    1. Researcher submits request
    2. Workflow processes through all states
    3. Admin approves at gates
    4. Data delivered
    """
    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)

    # Step 1: Researcher submits via portal
    request_id = await facade.process_new_request(
        researcher_request="Complete study request", researcher_info=sample_researcher_info
    )

    # Step 2: Track progress
    await asyncio.sleep(1.0)
    initial_status = await facade.get_request_status(request_id)
    initial_state = initial_status["current_state"]

    # Step 3: Process any approvals (simulating admin)
    for _ in range(3):  # Check up to 3 times for approvals
        await asyncio.sleep(1.0)

        async with get_db_session() as session:
            result = await session.execute(
                select(Approval)
                .where(Approval.request_id == request_id)
                .where(Approval.status == "pending")
            )
            pending_approvals = result.scalars().all()

            for approval in pending_approvals:
                # Admin approves
                await facade.process_approval_response(
                    approval_id=approval.id,
                    reviewer="admin@hospital.edu",
                    decision="approve",
                    notes="Auto-approved for E2E test",
                )

    # Step 4: Check final state
    await asyncio.sleep(2.0)
    final_status = await facade.get_request_status(request_id)
    final_state = final_status["current_state"]

    # Workflow should have progressed
    assert final_state != initial_state or final_state == "complete"

    await facade.close()


# ============================================================================
# Test: Error Handling in UI Context
# ============================================================================


@pytest.mark.asyncio
async def test_ui_handles_missing_request_gracefully():
    """Test that UI can handle requests that don't exist"""
    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)

    # Try to get status of non-existent request (simulating user typing wrong ID)
    status = await facade.get_request_status("INVALID-123")

    # Should return None, not raise exception
    assert status is None

    # UI would show "Request not found" message
    await facade.close()


@pytest.mark.asyncio
async def test_ui_handles_empty_active_requests():
    """Test that UI can handle when there are no active requests"""
    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)

    # Get active requests when none exist (new database)
    active = await facade.get_all_active_requests()

    # Should return empty list, not raise exception
    assert isinstance(active, list)
    # May or may not be empty depending on other tests

    await facade.close()


# ============================================================================
# Performance Test for UI Responsiveness
# ============================================================================


@pytest.mark.asyncio
async def test_ui_operations_are_responsive(sample_researcher_info):
    """Test that UI operations complete quickly for good UX"""
    import time

    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)

    # Test 1: Submit request should be < 1 second
    start = time.time()
    request_id = await facade.process_new_request(
        researcher_request="Test", researcher_info=sample_researcher_info
    )
    submit_time = time.time() - start

    assert submit_time < 1.0

    # Test 2: Get status should be < 0.5 seconds
    start = time.time()
    status = await facade.get_request_status(request_id)
    status_time = time.time() - start

    assert status_time < 0.5

    # Test 3: Get all active should be < 1 second
    start = time.time()
    active = await facade.get_all_active_requests()
    active_time = time.time() - start

    assert active_time < 1.0

    await facade.close()
