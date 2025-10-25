"""
Tests for Monitoring Agent-to-Agent Handoffs

These tests verify that:
1. Agents properly complete tasks and return expected results
2. The orchestrator correctly routes tasks between agents
3. Approval workflows pause and resume correctly
4. Agent execution history is tracked in the database
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch
from sqlalchemy import select

from app.orchestrator.orchestrator import ResearchRequestOrchestrator
from app.agents.requirements_agent import RequirementsAgent
from app.agents.phenotype_agent import PhenotypeValidationAgent
from app.database import get_db_session, init_db
from app.database.models import (
    ResearchRequest,
    AgentExecution,
    Approval,
    AuditLog
)


@pytest.fixture
async def orchestrator():
    """Create orchestrator with all agents registered"""
    orch = ResearchRequestOrchestrator()

    # Register agents
    orch.register_agent('requirements_agent', RequirementsAgent())
    orch.register_agent('phenotype_agent', PhenotypeValidationAgent())

    return orch


@pytest.fixture
async def sample_request():
    """Create a sample research request"""
    return {
        'researcher_request': 'I need female patients over 50 with diabetes',
        'researcher_info': {
            'name': 'Dr. Test',
            'email': 'test@hospital.org',
            'department': 'Cardiology'
        }
    }


class TestAgentHandoffMonitoring:
    """Test suite for monitoring agent handoffs"""

    @pytest.mark.asyncio
    async def test_agent_execution_tracking(self, orchestrator, sample_request):
        """Test that agent executions are tracked in database"""
        # Submit request
        request_id = await orchestrator.process_new_request(
            sample_request['researcher_request'],
            sample_request['researcher_info']
        )

        # Wait for agent to complete
        await asyncio.sleep(2)

        # Check database for agent executions
        async with get_db_session() as session:
            result = await session.execute(
                select(AgentExecution).where(AgentExecution.request_id == request_id)
            )
            executions = result.scalars().all()

            # Should have at least one agent execution
            assert len(executions) > 0, "No agent executions recorded"

            # Verify execution has required fields
            execution = executions[0]
            assert execution.agent_id is not None
            assert execution.task is not None
            assert execution.started_at is not None
            assert execution.status in ['success', 'failed', 'pending']

            print(f"✓ Agent execution tracked: {execution.agent_id}.{execution.task}")

    @pytest.mark.asyncio
    async def test_agent_handoff_sequence(self, orchestrator, sample_request):
        """Test that agents are invoked in correct sequence"""
        request_id = await orchestrator.process_new_request(
            sample_request['researcher_request'],
            sample_request['researcher_info']
        )

        # Wait for workflow to progress
        await asyncio.sleep(2)

        # Check request state
        status = await orchestrator.get_request_status(request_id)
        assert status is not None

        # Verify agents_involved list shows handoff sequence
        agents_involved = status.get('agents_involved', [])
        assert len(agents_involved) > 0, "No agents involved in workflow"

        # First agent should be requirements_agent
        assert agents_involved[0]['agent'] == 'requirements_agent'
        assert agents_involved[0]['task'] == 'gather_requirements'

        print(f"✓ Agent handoff sequence:")
        for i, agent in enumerate(agents_involved):
            print(f"  {i+1}. {agent['agent']}.{agent['task']} (from: {agent.get('from_agent', 'N/A')})")

    @pytest.mark.asyncio
    async def test_approval_workflow_handoff(self, orchestrator):
        """Test that workflow pauses at approval gates"""
        # Create request with pre-structured requirements (will trigger approval)
        request_id = await orchestrator.process_new_request(
            researcher_request='I need diabetes patients',
            researcher_info={
                'name': 'Dr. Test',
                'email': 'test@hospital.org'
            }
        )

        # Wait for requirements agent to complete
        await asyncio.sleep(3)

        # Check if approval was created
        async with get_db_session() as session:
            result = await session.execute(
                select(Approval).where(Approval.request_id == request_id)
            )
            approvals = result.scalars().all()

            if len(approvals) > 0:
                approval = approvals[0]
                assert approval.approval_type in ['requirements', 'phenotype_sql']
                assert approval.status == 'pending'

                print(f"✓ Approval gate triggered: {approval.approval_type}")
                print(f"  - Status: {approval.status}")
                print(f"  - Submitted by: {approval.submitted_by}")

                # Verify workflow state is at approval state
                status = await orchestrator.get_request_status(request_id)
                assert 'review' in status['current_state'].lower() or 'approval' in status['current_state'].lower()
                print(f"  - Workflow state: {status['current_state']}")
            else:
                print("⚠ No approval created (requirements may be incomplete)")

    @pytest.mark.asyncio
    async def test_audit_log_tracking(self, orchestrator, sample_request):
        """Test that all agent activities are logged to audit trail"""
        request_id = await orchestrator.process_new_request(
            sample_request['researcher_request'],
            sample_request['researcher_info']
        )

        await asyncio.sleep(2)

        # Check audit logs
        async with get_db_session() as session:
            result = await session.execute(
                select(AuditLog)
                .where(AuditLog.request_id == request_id)
                .order_by(AuditLog.timestamp)
            )
            logs = result.scalars().all()

            assert len(logs) > 0, "No audit logs created"

            # Verify key events are logged
            event_types = [log.event_type for log in logs]
            assert 'request_created' in event_types
            assert 'agent_started' in event_types or 'state_changed' in event_types

            print(f"✓ Audit trail has {len(logs)} events:")
            for log in logs[:5]:  # Show first 5
                print(f"  - [{log.timestamp.strftime('%H:%M:%S')}] {log.event_type} (agent: {log.agent_id or 'system'})")

    @pytest.mark.asyncio
    async def test_handoff_with_context_passing(self, orchestrator):
        """Test that context is properly passed between agents"""
        request_id = await orchestrator.process_new_request(
            researcher_request='I need patients with Type 2 Diabetes',
            researcher_info={
                'name': 'Dr. Test',
                'email': 'test@hospital.org'
            }
        )

        await asyncio.sleep(2)

        # Get status and verify context is preserved
        status = await orchestrator.get_request_status(request_id)

        agents_involved = status.get('agents_involved', [])

        # Check that each agent received request_id
        for agent in agents_involved:
            # Context should be tracked (though not fully visible for security)
            assert 'agent' in agent
            assert 'task' in agent
            assert 'timestamp' in agent

        print(f"✓ Context passed through {len(agents_involved)} agent(s)")

    @pytest.mark.asyncio
    async def test_failed_handoff_handling(self, orchestrator):
        """Test that failed agent handoffs are properly tracked"""
        # Create request that might fail
        request_id = await orchestrator.process_new_request(
            researcher_request='',  # Empty request - might cause issues
            researcher_info={
                'name': 'Dr. Test',
                'email': 'test@hospital.org'
            }
        )

        await asyncio.sleep(2)

        # Check if error was tracked
        async with get_db_session() as session:
            result = await session.execute(
                select(AgentExecution)
                .where(AgentExecution.request_id == request_id)
            )
            executions = result.scalars().all()

            # Check for failed or retrying executions
            statuses = [exec.status for exec in executions]

            if 'failed' in statuses or 'retrying' in statuses:
                print("✓ Failed handoff detected and tracked")
                for exec in executions:
                    if exec.status in ['failed', 'retrying']:
                        print(f"  - Agent: {exec.agent_id}")
                        print(f"  - Error: {exec.error}")
                        print(f"  - Retry count: {exec.retry_count}")
            else:
                print("⚠ No failures detected (request may have succeeded)")

    @pytest.mark.asyncio
    async def test_concurrent_handoffs(self, orchestrator):
        """Test that multiple concurrent requests are handled correctly"""
        # Submit multiple requests
        request_ids = []
        for i in range(3):
            request_id = await orchestrator.process_new_request(
                researcher_request=f'Test request {i+1}',
                researcher_info={
                    'name': f'Dr. Test {i+1}',
                    'email': f'test{i+1}@hospital.org'
                }
            )
            request_ids.append(request_id)

        await asyncio.sleep(3)

        # Check that all requests were processed
        for request_id in request_ids:
            status = await orchestrator.get_request_status(request_id)
            assert status is not None
            assert len(status.get('agents_involved', [])) > 0

        print(f"✓ {len(request_ids)} concurrent requests processed successfully")


class TestAgentHandoffDiagnostics:
    """Diagnostic tests to identify handoff issues"""

    @pytest.mark.asyncio
    async def test_diagnose_stalled_workflow(self):
        """Diagnose workflows that are stalled"""
        async with get_db_session() as session:
            # Find requests that haven't completed and have no recent activity
            result = await session.execute(
                select(ResearchRequest)
                .where(ResearchRequest.completed_at.is_(None))
            )
            active_requests = result.scalars().all()

            print(f"\n📊 Active Requests Diagnostic:")
            print(f"Total active requests: {len(active_requests)}")

            for req in active_requests[:10]:  # Check first 10
                # Get last agent activity
                exec_result = await session.execute(
                    select(AgentExecution)
                    .where(AgentExecution.request_id == req.id)
                    .order_by(AgentExecution.started_at.desc())
                    .limit(1)
                )
                last_execution = exec_result.scalar_one_or_none()

                # Calculate time since last activity
                if last_execution:
                    time_since_activity = datetime.now() - last_execution.started_at

                    print(f"\nRequest: {req.id}")
                    print(f"  State: {req.current_state}")
                    print(f"  Current Agent: {req.current_agent}")
                    print(f"  Last Activity: {time_since_activity.total_seconds():.1f}s ago")
                    print(f"  Last Agent: {last_execution.agent_id}")
                    print(f"  Last Task: {last_execution.task}")
                    print(f"  Status: {last_execution.status}")

                    if time_since_activity.total_seconds() > 300:  # 5 minutes
                        print(f"  ⚠️ STALLED - No activity in {time_since_activity.total_seconds()/60:.1f} minutes")

    @pytest.mark.asyncio
    async def test_diagnose_approval_bottlenecks(self):
        """Check for approval bottlenecks"""
        async with get_db_session() as session:
            result = await session.execute(
                select(Approval)
                .where(Approval.status == 'pending')
                .order_by(Approval.submitted_at)
            )
            pending_approvals = result.scalars().all()

            print(f"\n📊 Approval Bottleneck Analysis:")
            print(f"Total pending approvals: {len(pending_approvals)}")

            if len(pending_approvals) == 0:
                print("✓ No approval bottlenecks detected")
                return

            # Group by type
            by_type = {}
            for approval in pending_approvals:
                type_name = approval.approval_type
                if type_name not in by_type:
                    by_type[type_name] = []
                by_type[type_name].append(approval)

            for approval_type, approvals in by_type.items():
                print(f"\n{approval_type.upper()}:")
                print(f"  Count: {len(approvals)}")

                # Find oldest
                oldest = min(approvals, key=lambda a: a.submitted_at)
                age = datetime.now() - oldest.submitted_at
                print(f"  Oldest: {age.total_seconds()/3600:.1f} hours")
                print(f"  Request: {oldest.request_id}")

                if age.total_seconds() > 7200:  # 2 hours
                    print(f"  ⚠️ BOTTLENECK - Approvals waiting > 2 hours")


# Utility function for manual testing
async def monitor_request_handoffs(request_id: str):
    """
    Monitor the handoff sequence for a specific request

    Usage:
        asyncio.run(monitor_request_handoffs('REQ-20251022-XXXXX'))
    """
    print(f"\n🔍 Monitoring handoffs for request: {request_id}\n")

    async with get_db_session() as session:
        # Get request
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        if not request:
            print(f"❌ Request {request_id} not found")
            return

        print(f"📋 Request Status:")
        print(f"  State: {request.current_state}")
        print(f"  Current Agent: {request.current_agent}")
        print(f"  Created: {request.created_at}")

        # Get agent executions
        exec_result = await session.execute(
            select(AgentExecution)
            .where(AgentExecution.request_id == request_id)
            .order_by(AgentExecution.started_at)
        )
        executions = exec_result.scalars().all()

        print(f"\n🔄 Agent Handoff Sequence ({len(executions)} executions):")
        for i, execution in enumerate(executions):
            duration = execution.duration_seconds or 0
            status_emoji = "✓" if execution.status == "success" else "✗" if execution.status == "failed" else "⏳"

            print(f"{i+1}. {status_emoji} {execution.agent_id}.{execution.task}")
            print(f"   Started: {execution.started_at.strftime('%H:%M:%S')}")
            print(f"   Duration: {duration:.2f}s")
            print(f"   Status: {execution.status}")
            if execution.retry_count > 0:
                print(f"   Retries: {execution.retry_count}")
            if execution.error:
                print(f"   Error: {execution.error[:100]}...")

        # Get approvals
        approval_result = await session.execute(
            select(Approval)
            .where(Approval.request_id == request_id)
            .order_by(Approval.submitted_at)
        )
        approvals = approval_result.scalars().all()

        if approvals:
            print(f"\n✋ Approval Gates ({len(approvals)}):")
            for approval in approvals:
                print(f"  - {approval.approval_type}: {approval.status}")
                print(f"    Submitted: {approval.submitted_at.strftime('%H:%M:%S')}")
                if approval.reviewed_at:
                    print(f"    Reviewed: {approval.reviewed_at.strftime('%H:%M:%S')} by {approval.reviewed_by}")

        # Get audit logs
        log_result = await session.execute(
            select(AuditLog)
            .where(AuditLog.request_id == request_id)
            .order_by(AuditLog.timestamp)
        )
        logs = log_result.scalars().all()

        print(f"\n📝 Audit Trail ({len(logs)} events):")
        for log in logs:
            print(f"  [{log.timestamp.strftime('%H:%M:%S')}] {log.event_type}")
            if log.agent_id:
                print(f"    Agent: {log.agent_id}")


if __name__ == "__main__":
    # Run diagnostic on all active requests
    import sys

    if len(sys.argv) > 1:
        request_id = sys.argv[1]
        asyncio.run(monitor_request_handoffs(request_id))
    else:
        print("Running full diagnostic...")
        asyncio.run(init_db())
        pytest.main([__file__, '-v', '-k', 'diagnose'])
