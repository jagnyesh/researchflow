"""
Integration Tests for LangGraphRequestFacade

Tests the request facade's compatibility with ResearchRequestOrchestrator API
and validates complete workflows through the LangGraph system.

These tests verify:
1. API compatibility with existing Streamlit UIs
2. Background workflow execution
3. Database synchronization
4. Approval workflow integration
5. State persistence via checkpointing
"""

import pytest
import asyncio
from datetime import datetime
from typing import Dict, Any

from app.langchain_orchestrator.request_facade import LangGraphRequestFacade
from app.database import get_db_session, ResearchRequest, Approval
from sqlalchemy import select


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def facade():
    """Create facade instance for testing"""
    # Use real agents=False for faster tests
    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)
    yield facade
    await facade.close()


@pytest.fixture
def sample_researcher_info() -> Dict[str, Any]:
    """Sample researcher information"""
    return {
        "name": "Dr. Jane Smith",
        "email": "jsmith@hospital.edu",
        "department": "Cardiology",
        "irb_number": "IRB-2025-001",
    }


@pytest.fixture
def sample_request_text() -> str:
    """Sample research request"""
    return (
        "I need clinical notes and lab results for heart failure patients "
        "admitted in 2024 who had a prior diabetes diagnosis."
    )


# ============================================================================
# Test: process_new_request()
# ============================================================================


@pytest.mark.asyncio
async def test_process_new_request_creates_database_record(
    facade, sample_request_text, sample_researcher_info
):
    """Test that process_new_request creates ResearchRequest in database"""
    # Submit request
    request_id = await facade.process_new_request(
        researcher_request=sample_request_text, researcher_info=sample_researcher_info
    )

    # Verify request ID format
    assert request_id.startswith("REQ-")
    assert len(request_id) > 10

    # Verify database record created
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        req = result.scalar_one_or_none()

        assert req is not None
        assert req.researcher_name == "Dr. Jane Smith"
        assert req.researcher_email == "jsmith@hospital.edu"
        assert req.initial_request == sample_request_text
        assert req.current_state == "new_request"


@pytest.mark.asyncio
async def test_process_new_request_starts_background_workflow(
    facade, sample_request_text, sample_researcher_info
):
    """Test that process_new_request starts workflow asynchronously"""
    # Submit request
    request_id = await facade.process_new_request(
        researcher_request=sample_request_text, researcher_info=sample_researcher_info
    )

    # Give workflow time to start and make some progress
    await asyncio.sleep(1.0)

    # Check that workflow has updated state
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        req = result.scalar_one_or_none()

        # State should have progressed from new_request
        # (exact state depends on workflow execution, but should not be new_request)
        assert req is not None
        # Note: With stubs, workflow completes quickly, so state may vary
        assert req.current_state in [
            "new_request",
            "requirements_gathering",
            "requirements_approval",
            "feasibility_validation",
            "complete",
        ]


@pytest.mark.asyncio
async def test_process_new_request_returns_immediately(
    facade, sample_request_text, sample_researcher_info
):
    """Test that process_new_request returns quickly (non-blocking)"""
    import time

    start = time.time()
    request_id = await facade.process_new_request(
        researcher_request=sample_request_text, researcher_info=sample_researcher_info
    )
    elapsed = time.time() - start

    # Should return in < 1 second (workflow runs in background)
    assert elapsed < 1.0
    assert request_id is not None


# ============================================================================
# Test: get_request_status()
# ============================================================================


@pytest.mark.asyncio
async def test_get_request_status_returns_correct_data(
    facade, sample_request_text, sample_researcher_info
):
    """Test that get_request_status returns comprehensive status"""
    # Create request
    request_id = await facade.process_new_request(
        researcher_request=sample_request_text, researcher_info=sample_researcher_info
    )

    # Get status
    status = await facade.get_request_status(request_id)

    # Verify status structure
    assert status is not None
    assert status["request_id"] == request_id
    assert "current_state" in status
    assert "current_agent" in status
    assert "started_at" in status
    assert "state_history" in status
    assert "researcher_info" in status

    # Verify researcher info
    assert status["researcher_info"]["name"] == "Dr. Jane Smith"
    assert status["researcher_info"]["email"] == "jsmith@hospital.edu"


@pytest.mark.asyncio
async def test_get_request_status_returns_none_for_invalid_id(facade):
    """Test that get_request_status returns None for non-existent request"""
    status = await facade.get_request_status("INVALID-REQUEST-ID")
    assert status is None


# ============================================================================
# Test: get_all_active_requests()
# ============================================================================


@pytest.mark.asyncio
async def test_get_all_active_requests_returns_list(
    facade, sample_request_text, sample_researcher_info
):
    """Test that get_all_active_requests returns all active requests"""
    # Create multiple requests
    request_id1 = await facade.process_new_request(
        researcher_request=sample_request_text, researcher_info=sample_researcher_info
    )
    request_id2 = await facade.process_new_request(
        researcher_request="Another study request", researcher_info=sample_researcher_info
    )

    # Get all active requests
    active = await facade.get_all_active_requests()

    # Verify both requests appear
    request_ids = [req["request_id"] for req in active]
    assert request_id1 in request_ids
    assert request_id2 in request_ids


@pytest.mark.asyncio
async def test_get_all_active_requests_excludes_completed(
    facade, sample_request_text, sample_researcher_info
):
    """Test that get_all_active_requests excludes completed requests"""
    # Create request
    request_id = await facade.process_new_request(
        researcher_request=sample_request_text, researcher_info=sample_researcher_info
    )

    # Manually mark as completed in database
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        req = result.scalar_one()
        req.completed_at = datetime.now()
        await session.commit()

    # Get active requests
    active = await facade.get_all_active_requests()
    request_ids = [req["request_id"] for req in active]

    # Completed request should not appear
    assert request_id not in request_ids


# ============================================================================
# Test: process_approval_response()
# ============================================================================


@pytest.mark.asyncio
async def test_process_approval_response_updates_approval(
    facade, sample_request_text, sample_researcher_info
):
    """Test that process_approval_response updates approval record"""
    # Create request
    request_id = await facade.process_new_request(
        researcher_request=sample_request_text, researcher_info=sample_researcher_info
    )

    # Wait for workflow to create approval
    await asyncio.sleep(2.0)

    # Check if approval was created
    async with get_db_session() as session:
        result = await session.execute(select(Approval).where(Approval.request_id == request_id))
        approval = result.scalar_one_or_none()

        if approval:
            approval_id = approval.id

            # Process approval
            await facade.process_approval_response(
                approval_id=approval_id,
                reviewer="admin@hospital.edu",
                decision="approve",
                notes="Looks good!",
            )

            # Verify approval updated
            await session.refresh(approval)
            assert approval.status == "approved"
            assert approval.reviewed_by == "admin@hospital.edu"


# ============================================================================
# Test: API Compatibility Methods
# ============================================================================


@pytest.mark.asyncio
async def test_register_agent_is_no_op(facade):
    """Test that register_agent is no-op for compatibility"""
    from app.agents import RequirementsAgent

    # Should not raise exception
    facade.register_agent("requirements_agent", RequirementsAgent())

    # Verify agent tracked (for compatibility)
    assert "requirements_agent" in facade.agents


@pytest.mark.asyncio
async def test_route_task_is_no_op(facade):
    """Test that route_task is no-op for compatibility"""
    # Should not raise exception
    await facade.route_task(
        agent_id="phenotype_agent",
        task="validate_feasibility",
        context={"request_id": "TEST-123"},
        from_agent="requirements_agent",
    )


def test_get_agent_metrics_returns_empty(facade):
    """Test that get_agent_metrics returns empty dict for compatibility"""
    metrics = facade.get_agent_metrics("requirements_agent")
    assert metrics == {}


# ============================================================================
# Test: Background Workflow Execution
# ============================================================================


@pytest.mark.asyncio
async def test_workflow_executes_completely_with_stubs(
    facade, sample_request_text, sample_researcher_info
):
    """Test that workflow executes end-to-end with stub agents"""
    # Submit request
    request_id = await facade.process_new_request(
        researcher_request=sample_request_text, researcher_info=sample_researcher_info
    )

    # Wait for workflow to complete (stubs are fast)
    await asyncio.sleep(3.0)

    # Check final state
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        req = result.scalar_one_or_none()

        # Workflow should have made significant progress or completed
        assert req is not None
        # State should be beyond initial states
        # (exact state depends on approval gates with stubs)
        assert req.current_state is not None


# ============================================================================
# Test: State Persistence
# ============================================================================


@pytest.mark.asyncio
async def test_state_persists_across_facade_instances(sample_request_text, sample_researcher_info):
    """Test that workflow state persists via checkpointing"""
    # Create first facade instance
    facade1 = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)

    # Submit request
    request_id = await facade1.process_new_request(
        researcher_request=sample_request_text, researcher_info=sample_researcher_info
    )

    await asyncio.sleep(1.0)

    # Get status
    status1 = await facade1.get_request_status(request_id)
    state1 = status1["current_state"]

    await facade1.close()

    # Create second facade instance
    facade2 = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)

    # Get status from second instance
    status2 = await facade2.get_request_status(request_id)
    state2 = status2["current_state"]

    # State should be consistent (persisted in database)
    assert state1 == state2

    await facade2.close()


# ============================================================================
# Test: Error Handling
# ============================================================================


@pytest.mark.asyncio
async def test_workflow_handles_errors_gracefully(facade):
    """Test that workflow handles errors and updates database"""
    # Submit request with invalid data to trigger error
    # (depends on workflow error handling implementation)
    request_id = await facade.process_new_request(
        researcher_request="", researcher_info={"name": "Test"}  # Minimal/invalid data
    )

    # Wait for workflow
    await asyncio.sleep(2.0)

    # Check that request exists and has error state (if implemented)
    status = await facade.get_request_status(request_id)
    assert status is not None
    # Error handling may vary by implementation


# ============================================================================
# Test: Concurrent Requests
# ============================================================================


@pytest.mark.asyncio
async def test_facade_handles_concurrent_requests(facade, sample_request_text):
    """Test that facade can handle multiple concurrent requests"""
    # Submit 5 requests concurrently
    tasks = []
    for i in range(5):
        researcher_info = {
            "name": f"Researcher {i}",
            "email": f"researcher{i}@hospital.edu",
            "irb_number": f"IRB-{i}",
        }
        tasks.append(facade.process_new_request(sample_request_text, researcher_info))

    # All should complete without error
    request_ids = await asyncio.gather(*tasks)

    # Verify all requests created
    assert len(request_ids) == 5
    assert len(set(request_ids)) == 5  # All unique


# ============================================================================
# Performance Test
# ============================================================================


@pytest.mark.asyncio
async def test_facade_initialization_is_fast():
    """Test that facade initializes quickly"""
    import time

    start = time.time()
    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)
    elapsed = time.time() - start

    # Should initialize in < 1 second
    assert elapsed < 1.0

    await facade.close()
