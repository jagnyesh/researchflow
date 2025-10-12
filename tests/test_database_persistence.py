"""
Integration Tests for Database Persistence

Tests that verify:
- Database initialization
- ResearchRequest CRUD operations
- AuditLog creation and querying
- Orchestrator database persistence
- State transitions persist correctly
"""

import pytest
import asyncio
import uuid
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import attributes

from app.database import (
    get_db_session,
    init_db,
    drop_db,
    ResearchRequest,
    AuditLog,
    RequirementsData,
    FeasibilityReport
)
from app.orchestrator.workflow_engine import WorkflowState


def generate_request_id(prefix="TEST"):
    """Generate unique request ID for tests"""
    return f"REQ-{prefix}-{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture(scope="function", autouse=True)
async def clean_database():
    """
    Clean database fixture - drops and recreates tables before each test

    Uses autouse=True to automatically clean database for all tests in this module
    """
    # Drop and recreate database
    await drop_db()
    await init_db()

    yield

    # Cleanup after test
    await drop_db()


@pytest.mark.asyncio
async def test_database_initialization():
    """
    Test that database tables are created successfully
    """
    # Verify we can create a session and query tables
    async with get_db_session() as session:
        # Query research_requests table
        result = await session.execute(select(ResearchRequest))
        requests = result.scalars().all()
        assert requests == []

        # Query audit_logs table
        result = await session.execute(select(AuditLog))
        logs = result.scalars().all()
        assert logs == []


@pytest.mark.asyncio
async def test_create_research_request():
    """
    Test creating a ResearchRequest in the database
    """
    async with get_db_session() as session:
        # Create research request
        request = ResearchRequest(
            id="REQ-20251009-TEST001",
            researcher_name="Dr. Test Researcher",
            researcher_email="test@example.com",
            researcher_department="Oncology",
            irb_number="IRB-2025-001",
            initial_request="I need all patients with diabetes",
            current_state=WorkflowState.NEW_REQUEST.value,
            current_agent=None,
            agents_involved=[],
            state_history=[{
                'state': WorkflowState.NEW_REQUEST.value,
                'timestamp': datetime.now().isoformat()
            }]
        )

        session.add(request)
        await session.commit()

        # Verify it was created
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == "REQ-20251009-TEST001")
        )
        retrieved_request = result.scalar_one()

        assert retrieved_request.id == "REQ-20251009-TEST001"
        assert retrieved_request.researcher_name == "Dr. Test Researcher"
        assert retrieved_request.researcher_email == "test@example.com"
        assert retrieved_request.researcher_department == "Oncology"
        assert retrieved_request.irb_number == "IRB-2025-001"
        assert retrieved_request.current_state == WorkflowState.NEW_REQUEST.value
        assert retrieved_request.state_history is not None
        assert len(retrieved_request.state_history) == 1


@pytest.mark.asyncio
async def test_create_audit_log():
    """
    Test creating AuditLog entries
    """
    async with get_db_session() as session:
        # Create research request first
        request = ResearchRequest(
            id="REQ-20251009-TEST002",
            researcher_name="Dr. Test",
            researcher_email="test@example.com",
            initial_request="Test request",
            current_state=WorkflowState.NEW_REQUEST.value
        )
        session.add(request)
        await session.flush()

        # Create audit log entry
        audit_entry = AuditLog(
            request_id="REQ-20251009-TEST002",
            event_type="request_created",
            event_data={
                'researcher_name': 'Dr. Test',
                'initial_request': 'Test request'
            },
            triggered_by='orchestrator',
            severity='info'
        )
        session.add(audit_entry)
        await session.commit()

        # Verify audit log was created
        result = await session.execute(
            select(AuditLog).where(AuditLog.request_id == "REQ-20251009-TEST002")
        )
        logs = result.scalars().all()

        assert len(logs) == 1
        assert logs[0].event_type == "request_created"
        assert logs[0].triggered_by == "orchestrator"
        assert logs[0].severity == "info"
        assert logs[0].event_data['researcher_name'] == 'Dr. Test'


@pytest.mark.asyncio
async def test_update_research_request_state():
    """
    Test updating ResearchRequest state and state_history
    """
    async with get_db_session() as session:
        # Create initial request
        request = ResearchRequest(
            id="REQ-20251009-TEST003",
            researcher_name="Dr. Test",
            researcher_email="test@example.com",
            initial_request="Test request",
            current_state=WorkflowState.NEW_REQUEST.value,
            state_history=[{
                'state': WorkflowState.NEW_REQUEST.value,
                'timestamp': datetime.now().isoformat()
            }]
        )
        session.add(request)
        await session.commit()

    # Update state in separate transaction
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == "REQ-20251009-TEST003")
        )
        request = result.scalar_one()

        # Update state
        request.current_state = WorkflowState.REQUIREMENTS_GATHERING.value
        request.current_agent = "requirements_agent"

        # Append to state_history
        state_history = request.state_history or []
        state_history.append({
            'state': WorkflowState.REQUIREMENTS_GATHERING.value,
            'timestamp': datetime.now().isoformat()
        })
        request.state_history = state_history

        # Mark JSON column as modified so SQLAlchemy persists it
        attributes.flag_modified(request, 'state_history')

        await session.commit()

    # Verify update persisted
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == "REQ-20251009-TEST003")
        )
        request = result.scalar_one()

        assert request.current_state == WorkflowState.REQUIREMENTS_GATHERING.value
        assert request.current_agent == "requirements_agent"
        assert len(request.state_history) == 2
        assert request.state_history[1]['state'] == WorkflowState.REQUIREMENTS_GATHERING.value


@pytest.mark.asyncio
async def test_query_active_requests():
    """
    Test querying active (not completed) requests
    """
    # Generate unique IDs for this test
    completed_id = generate_request_id("COMPLETED")
    active_ids = [generate_request_id(f"ACTIVE{i}") for i in range(3)]

    async with get_db_session() as session:
        # Create completed request
        completed_request = ResearchRequest(
            id=completed_id,
            researcher_name="Dr. Test",
            researcher_email="test@example.com",
            initial_request="Completed request",
            current_state=WorkflowState.DELIVERED.value,
            completed_at=datetime.now()
        )
        session.add(completed_request)

        # Create active requests
        for i, active_id in enumerate(active_ids):
            active_request = ResearchRequest(
                id=active_id,
                researcher_name=f"Dr. Test {i}",
                researcher_email=f"test{i}@example.com",
                initial_request=f"Active request {i}",
                current_state=WorkflowState.REQUIREMENTS_GATHERING.value,
                completed_at=None  # Not completed
            )
            session.add(active_request)

        await session.commit()

    # Query active requests
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.completed_at.is_(None))
        )
        active_requests = result.scalars().all()

        assert len(active_requests) == 3
        for req in active_requests:
            assert req.completed_at is None
            assert req.id in active_ids


@pytest.mark.asyncio
async def test_audit_log_querying():
    """
    Test querying AuditLog entries by request_id and event_type
    """
    async with get_db_session() as session:
        # Create research request
        request = ResearchRequest(
            id="REQ-20251009-AUDIT",
            researcher_name="Dr. Test",
            researcher_email="test@example.com",
            initial_request="Test request",
            current_state=WorkflowState.NEW_REQUEST.value
        )
        session.add(request)
        await session.flush()

        # Create multiple audit log entries
        events = [
            ("request_created", "orchestrator", "info"),
            ("agent_started", "requirements_agent", "info"),
            ("state_changed", "requirements_agent", "info"),
            ("workflow_error", "requirements_agent", "error")
        ]

        for event_type, triggered_by, severity in events:
            audit_entry = AuditLog(
                request_id="REQ-20251009-AUDIT",
                event_type=event_type,
                triggered_by=triggered_by,
                severity=severity,
                event_data={"test": "data"}
            )
            session.add(audit_entry)

        await session.commit()

    # Query all audit logs for request
    async with get_db_session() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.request_id == "REQ-20251009-AUDIT")
        )
        all_logs = result.scalars().all()
        assert len(all_logs) == 4

    # Query error logs only
    async with get_db_session() as session:
        result = await session.execute(
            select(AuditLog).where(
                AuditLog.request_id == "REQ-20251009-AUDIT",
                AuditLog.severity == "error"
            )
        )
        error_logs = result.scalars().all()
        assert len(error_logs) == 1
        assert error_logs[0].event_type == "workflow_error"


@pytest.mark.asyncio
async def test_complete_workflow_lifecycle():
    """
    Test complete workflow lifecycle from creation to completion
    """
    request_id = "REQ-20251009-LIFECYCLE"

    # Step 1: Create new request
    async with get_db_session() as session:
        request = ResearchRequest(
            id=request_id,
            researcher_name="Dr. Test",
            researcher_email="test@example.com",
            initial_request="Test workflow",
            current_state=WorkflowState.NEW_REQUEST.value,
            agents_involved=[],
            state_history=[{
                'state': WorkflowState.NEW_REQUEST.value,
                'timestamp': datetime.now().isoformat()
            }]
        )
        session.add(request)

        # Log creation
        audit = AuditLog(
            request_id=request_id,
            event_type="request_created",
            triggered_by="orchestrator",
            severity="info"
        )
        session.add(audit)
        await session.commit()

    # Step 2: Start requirements gathering
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one()

        request.current_state = WorkflowState.REQUIREMENTS_GATHERING.value
        request.current_agent = "requirements_agent"

        agents_involved = request.agents_involved or []
        agents_involved.append({
            'agent': 'requirements_agent',
            'task': 'gather_requirements',
            'timestamp': datetime.now().isoformat()
        })
        request.agents_involved = agents_involved
        attributes.flag_modified(request, 'agents_involved')

        state_history = request.state_history or []
        state_history.append({
            'state': WorkflowState.REQUIREMENTS_GATHERING.value,
            'timestamp': datetime.now().isoformat()
        })
        request.state_history = state_history
        attributes.flag_modified(request, 'state_history')

        # Log state change
        audit = AuditLog(
            request_id=request_id,
            event_type="state_changed",
            agent_id="requirements_agent",
            triggered_by="requirements_agent",
            severity="info"
        )
        session.add(audit)
        await session.commit()

    # Step 3: Complete workflow
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one()

        request.current_state = WorkflowState.DELIVERED.value
        request.completed_at = datetime.now()
        request.final_state = WorkflowState.DELIVERED.value

        state_history = request.state_history or []
        state_history.append({
            'state': WorkflowState.DELIVERED.value,
            'timestamp': datetime.now().isoformat()
        })
        request.state_history = state_history
        attributes.flag_modified(request, 'state_history')

        # Log completion
        audit = AuditLog(
            request_id=request_id,
            event_type="workflow_completed",
            triggered_by="orchestrator",
            severity="info",
            event_data={
                'final_state': WorkflowState.DELIVERED.value
            }
        )
        session.add(audit)
        await session.commit()

    # Verify final state
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one()

        assert request.current_state == WorkflowState.DELIVERED.value
        assert request.final_state == WorkflowState.DELIVERED.value
        assert request.completed_at is not None
        assert len(request.state_history) == 3
        assert len(request.agents_involved) == 1

        # Verify audit trail
        result = await session.execute(
            select(AuditLog).where(AuditLog.request_id == request_id)
        )
        audit_logs = result.scalars().all()

        assert len(audit_logs) == 3
        event_types = [log.event_type for log in audit_logs]
        assert "request_created" in event_types
        assert "state_changed" in event_types
        assert "workflow_completed" in event_types


@pytest.mark.asyncio
async def test_session_rollback_on_error():
    """
    Test that database session rolls back on error
    """
    # Try to create invalid request (should fail and rollback)
    try:
        async with get_db_session() as session:
            request = ResearchRequest(
                id="REQ-TEST-ROLLBACK",
                researcher_name="Dr. Test",
                researcher_email="test@example.com",
                initial_request="Test request",
                current_state=WorkflowState.NEW_REQUEST.value
            )
            session.add(request)
            await session.flush()

            # Force an error
            raise ValueError("Simulated error")
    except ValueError:
        pass

    # Verify request was NOT persisted (rolled back)
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == "REQ-TEST-ROLLBACK")
        )
        request = result.scalar_one_or_none()

        assert request is None  # Should not exist due to rollback


@pytest.mark.asyncio
async def test_multiple_concurrent_sessions():
    """
    Test that multiple concurrent database sessions work correctly
    """
    async def create_request(request_id: str):
        """Create a request in its own session"""
        async with get_db_session() as session:
            request = ResearchRequest(
                id=request_id,
                researcher_name=f"Dr. Test {request_id}",
                researcher_email=f"test{request_id}@example.com",
                initial_request=f"Test request {request_id}",
                current_state=WorkflowState.NEW_REQUEST.value
            )
            session.add(request)
            await session.commit()

    # Create multiple requests concurrently
    await asyncio.gather(
        create_request("REQ-CONCURRENT-1"),
        create_request("REQ-CONCURRENT-2"),
        create_request("REQ-CONCURRENT-3")
    )

    # Verify all were created
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(
                ResearchRequest.id.like("REQ-CONCURRENT-%")
            )
        )
        requests = result.scalars().all()

        assert len(requests) == 3
        ids = [req.id for req in requests]
        assert "REQ-CONCURRENT-1" in ids
        assert "REQ-CONCURRENT-2" in ids
        assert "REQ-CONCURRENT-3" in ids


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
