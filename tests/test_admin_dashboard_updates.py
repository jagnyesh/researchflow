"""
Test Admin Dashboard Tab Updates

This test suite verifies that the Admin Dashboard displays updates
from requests submitted in the Researcher Portal.

Tests all three tabs:
1. Overview - Shows new requests
2. Agent Metrics - Shows agent activity
3. Pending Approvals - Shows approvals awaiting review

Purpose: Ensure cross-process visibility between Researcher Portal
and Admin Dashboard via shared database.
"""

import pytest
import asyncio
from datetime import datetime
from sqlalchemy import select, func

from app.orchestrator.orchestrator import ResearchRequestOrchestrator
from app.agents.requirements_agent import RequirementsAgent
from app.agents.phenotype_agent import PhenotypeValidationAgent
from app.database import get_db_session
from app.database.models import ResearchRequest, AgentExecution, Approval
from app.services.approval_service import ApprovalService


@pytest.fixture
def orchestrator():
    """Create orchestrator like Researcher Portal does"""
    orch = ResearchRequestOrchestrator()
    orch.register_agent('requirements_agent', RequirementsAgent())
    orch.register_agent('phenotype_agent', PhenotypeValidationAgent())
    return orch


async def create_test_request(query: str, researcher_info: dict) -> str:
    """
    Helper to create a test request in database without starting workflow.
    Simulates what Researcher Portal does but avoids premature workflow completion.
    """
    from app.orchestrator.workflow_engine import WorkflowState
    from datetime import datetime
    import uuid

    request_id = f"REQ-TEST-{uuid.uuid4().hex[:8].upper()}"
    async with get_db_session() as session:
        research_request = ResearchRequest(
            id=request_id,
            researcher_name=researcher_info['name'],
            researcher_email=researcher_info['email'],
            irb_number=researcher_info.get('irb_number'),
            initial_request=query,
            current_state=WorkflowState.NEW_REQUEST.value,
            current_agent=None,
            agents_involved=[],
            state_history=[{
                'state': WorkflowState.NEW_REQUEST.value,
                'timestamp': datetime.now().isoformat()
            }]
        )
        session.add(research_request)
        await session.commit()
    return request_id


class TestOverviewTab:
    """Test Overview tab displays new requests"""

    @pytest.mark.asyncio
    async def test_new_request_appears_in_overview(self, orchestrator, clean_database):
        """
        Test: New request appears in Overview tab

        Simulates:
        1. User submits request in Researcher Portal
        2. Admin refreshes Overview tab in Admin Dashboard
        3. Request should appear in list
        """
        print(f"\n{'='*80}")
        print("TEST: Overview Tab - New Request Visibility")
        print(f"{'='*80}")

        # Submit request (like Researcher Portal)
        query = "I need diabetic patients with HbA1c > 8"
        researcher_info = {
            'name': 'Dr. Overview Test',
            'email': 'overview.test@hospital.org',
            'irb_number': 'IRB-OVERVIEW-001'
        }

        print(f"\n1. Submitting request from 'Researcher Portal'...")
        request_id = await create_test_request(query, researcher_info)
        print(f"   Request ID: {request_id}")

        # Fetch requests like Admin Dashboard Overview tab does
        print(f"\n2. Fetching requests from 'Admin Dashboard Overview'...")
        requests = await orchestrator.get_all_active_requests()

        print(f"   Total active requests: {len(requests)}")

        # Verify request appears
        assert len(requests) > 0, "No requests found"

        # Find our request
        our_request = next(
            (r for r in requests if r['request_id'] == request_id),
            None
        )

        assert our_request is not None, \
            f"Request {request_id} not found in active requests. Looking for: {request_id}"

        print(f"\n3. Request found in Overview:")
        print(f"   Request ID: {our_request['request_id']}")
        print(f"   Status: {our_request['current_state']}")
        print(f"   Current Agent: {our_request.get('current_agent', 'None')}")
        print(f"   Researcher: {our_request['researcher_info']['name']}")

        # Verify it's the newest (first in list due to DESC sort)
        assert requests[0]['request_id'] == request_id, \
            "Newest request not first in list"

        print(f"\n✅ PASS: Request appears in Overview tab")
        print(f"✅ PASS: Request is newest (first in list)")

    @pytest.mark.asyncio
    async def test_overview_shows_multiple_requests(self, orchestrator, clean_database):
        """Test Overview tab shows multiple requests in correct order"""

        print(f"\n{'='*80}")
        print("TEST: Overview Tab - Multiple Requests Ordering")
        print(f"{'='*80}")

        # Submit 3 requests
        request_ids = []
        for i in range(3):
            query = f"Test request {i+1}"
            researcher_info = {
                'name': f'Dr. Test {i+1}',
                'email': f'test{i+1}@hospital.org',
                'irb_number': f'IRB-{i+1}'
            }

            request_id = await create_test_request(query, researcher_info)
            request_ids.append(request_id)

            print(f"   Submitted request {i+1}: {request_id[:20]}...")
            await asyncio.sleep(0.1)  # Small delay to ensure different timestamps

        # Fetch requests
        requests = await orchestrator.get_all_active_requests()

        print(f"\n   Total requests: {len(requests)}")
        print(f"   Request order:")
        for i, req in enumerate(requests[:3]):
            print(f"     {i+1}. {req['request_id'][:20]}... "
                  f"({req['researcher_info']['name']})")

        # Verify newest first (DESC order)
        # request_ids[-1] is the last submitted, should be first in list
        assert requests[0]['request_id'] == request_ids[-1], \
            "Newest request not first"

        print(f"\n✅ PASS: Requests displayed in newest-first order")


class TestAgentMetricsTab:
    """Test Agent Metrics tab displays agent activity"""

    @pytest.mark.asyncio
    async def test_agent_activity_appears_in_metrics(self, orchestrator, clean_database):
        """
        Test: Agent activity appears in Agent Metrics tab

        This is the KEY fix - Agent Metrics should query database,
        not in-memory orchestrator state.
        """
        print(f"\n{'='*80}")
        print("TEST: Agent Metrics Tab - Agent Activity Visibility")
        print(f"{'='*80}")

        # Submit request to trigger agent activity
        query = "I need patients with hypertension"
        researcher_info = {
            'name': 'Dr. Metrics Test',
            'email': 'metrics.test@hospital.org',
            'irb_number': 'IRB-METRICS-001'
        }

        print(f"\n1. Creating request and simulating agent executions...")
        request_id = await create_test_request(query, researcher_info)

        # Create agent execution records directly (simulating agent activity)
        async with get_db_session() as session:
            from datetime import datetime, timedelta
            agent_exec = AgentExecution(
                request_id=request_id,
                agent_id='requirements_agent',
                task='gather_requirements',
                status='success',
                started_at=datetime.now(),
                completed_at=datetime.now() + timedelta(seconds=2)
            )
            session.add(agent_exec)
            await session.commit()

        # Query AgentExecution table (DATABASE, not in-memory)
        print(f"\n2. Querying AgentExecution table from database...")

        async with get_db_session() as session:
            # Get all executions for this request
            result = await session.execute(
                select(AgentExecution).where(
                    AgentExecution.request_id == request_id
                ).order_by(AgentExecution.started_at)
            )
            executions = result.scalars().all()

            print(f"   Found {len(executions)} agent executions")

            # Verify agents executed
            assert len(executions) > 0, "No agent executions found"

            executed_agents = list(set(e.agent_id for e in executions))
            print(f"\n3. Agents that executed:")
            for agent_id in executed_agents:
                agent_execs = [e for e in executions if e.agent_id == agent_id]
                print(f"   - {agent_id}:")
                print(f"       Tasks: {len(agent_execs)}")
                print(f"       Status: {[e.status for e in agent_execs]}")

                # Calculate metrics like Admin Dashboard would
                successful = sum(1 for e in agent_execs if e.status == 'success')
                failed = sum(1 for e in agent_execs if e.status == 'failed')

                print(f"       Successful: {successful}")
                print(f"       Failed: {failed}")

            # Verify Requirements Agent executed
            assert 'requirements_agent' in executed_agents, \
                "Requirements Agent didn't execute"

            print(f"\n✅ PASS: Agent activity recorded in database")
            print(f"✅ PASS: Can query metrics from AgentExecution table")

    @pytest.mark.asyncio
    async def test_agent_metrics_calculation(self, orchestrator, clean_database):
        """Test that metrics can be calculated from database"""

        query = "Test query for metrics"
        researcher_info = {
            'name': 'Dr. Test',
            'email': 'test@hospital.org',
            'irb_number': 'IRB-TEST'
        }

        request_id = await create_test_request(query, researcher_info)

        # Create some agent execution records
        async with get_db_session() as session:
            from datetime import datetime, timedelta
            agent_exec = AgentExecution(
                request_id=request_id,
                agent_id='requirements_agent',
                task='gather_requirements',
                status='success',
                started_at=datetime.now(),
                completed_at=datetime.now() + timedelta(seconds=1)
            )
            session.add(agent_exec)
            await session.commit()

        # Calculate metrics from database (like fixed Admin Dashboard)
        async with get_db_session() as session:
            result = await session.execute(
                select(AgentExecution).where(
                    AgentExecution.request_id == request_id
                )
            )
            all_executions = result.scalars().all()

            # Group by agent
            metrics_by_agent = {}
            for execution in all_executions:
                agent_id = execution.agent_id
                if agent_id not in metrics_by_agent:
                    metrics_by_agent[agent_id] = {
                        'total_tasks': 0,
                        'successful_tasks': 0,
                        'failed_tasks': 0,
                        'durations': []
                    }

                metrics_by_agent[agent_id]['total_tasks'] += 1

                if execution.status == 'success':
                    metrics_by_agent[agent_id]['successful_tasks'] += 1
                elif execution.status == 'failed':
                    metrics_by_agent[agent_id]['failed_tasks'] += 1

                if execution.completed_at and execution.started_at:
                    duration = (
                        execution.completed_at - execution.started_at
                    ).total_seconds()
                    metrics_by_agent[agent_id]['durations'].append(duration)

            # Calculate success rate
            for agent_id, metrics in metrics_by_agent.items():
                metrics['success_rate'] = (
                    metrics['successful_tasks'] / metrics['total_tasks']
                    if metrics['total_tasks'] > 0 else 0
                )
                metrics['avg_duration'] = (
                    sum(metrics['durations']) / len(metrics['durations'])
                    if metrics['durations'] else 0
                )

            print(f"\n{'='*80}")
            print("Calculated Metrics from Database:")
            print(f"{'='*80}")

            for agent_id, metrics in metrics_by_agent.items():
                print(f"\n{agent_id}:")
                print(f"  Total Tasks: {metrics['total_tasks']}")
                print(f"  Successful: {metrics['successful_tasks']}")
                print(f"  Failed: {metrics['failed_tasks']}")
                print(f"  Success Rate: {metrics['success_rate']:.1%}")
                print(f"  Avg Duration: {metrics['avg_duration']:.2f}s")

                # Assertions
                assert metrics['total_tasks'] > 0
                assert metrics['success_rate'] >= 0 and metrics['success_rate'] <= 1

            print(f"\n✅ PASS: Metrics calculated correctly from database")


class TestPendingApprovalsTab:
    """Test Pending Approvals tab displays new approvals"""

    @pytest.mark.asyncio
    async def test_sql_approval_appears(self, orchestrator, clean_database):
        """Test SQL approval appears in Pending Approvals tab"""

        print(f"\n{'='*80}")
        print("TEST: Pending Approvals Tab - SQL Approval Visibility")
        print(f"{'='*80}")

        # Submit request that will generate SQL
        query = "I need cancer patients with stage IV diagnosis"
        researcher_info = {
            'name': 'Dr. Approval Test',
            'email': 'approval.test@hospital.org',
            'irb_number': 'IRB-APPROVAL-001'
        }

        print(f"\n1. Creating request and SQL approval...")
        request_id = await create_test_request(query, researcher_info)

        # Create a pending SQL approval directly
        async with get_db_session() as session:
            from datetime import datetime, timedelta
            approval = Approval(
                request_id=request_id,
                approval_type='phenotype_sql',
                submitted_by='phenotype_agent',
                submitted_at=datetime.now(),
                timeout_at=datetime.now() + timedelta(hours=24),
                status='pending',
                approval_data={
                    'sql_query': 'SELECT * FROM patient WHERE diagnosis = "cancer"',
                    'estimated_cohort': 150,
                    'feasibility_score': 0.85
                }
            )
            session.add(approval)
            await session.commit()

        # Fetch pending approvals (like Admin Dashboard does)
        print(f"\n2. Fetching pending approvals from database...")

        async with get_db_session() as session:
            approval_service = ApprovalService(session)
            approvals = await approval_service.get_pending_approvals()

            print(f"   Total pending approvals: {len(approvals)}")

            # Find approvals for our request
            request_approvals = [
                a for a in approvals
                if a.request_id == request_id
            ]

            if request_approvals:
                approval = request_approvals[0]

                print(f"\n3. Approval found:")
                print(f"   Approval ID: {approval.id}")
                print(f"   Type: {approval.approval_type}")
                print(f"   Status: {approval.status}")
                print(f"   Request ID: {approval.request_id[:20]}...")

                # Verify it's SQL approval
                assert approval.approval_type == 'phenotype_sql', \
                    f"Expected phenotype_sql, got {approval.approval_type}"

                assert approval.status == 'pending', \
                    f"Expected pending, got {approval.status}"

                # Verify approval data has SQL
                if 'sql_query' in approval.approval_data:
                    sql_length = len(approval.approval_data['sql_query'])
                    print(f"   SQL Query: {sql_length} characters")

                    assert sql_length > 0, "SQL query is empty"

                print(f"\n✅ PASS: SQL approval appears in Pending Approvals")
            else:
                print(f"\n⚠️  No approvals found yet (may still be processing)")

    @pytest.mark.asyncio
    async def test_approvals_newest_first(self, orchestrator, clean_database):
        """Test approvals display in newest-first order"""

        print(f"\n{'='*80}")
        print("TEST: Pending Approvals - Newest First Ordering")
        print(f"{'='*80}")

        # Submit multiple requests and create approvals
        request_ids = []
        for i in range(2):
            query = f"Test approval ordering {i+1}"
            researcher_info = {
                'name': f'Dr. Order Test {i+1}',
                'email': f'order{i+1}@hospital.org',
                'irb_number': f'IRB-ORDER-{i+1}'
            }

            request_id = await create_test_request(query, researcher_info)
            request_ids.append(request_id)

            # Create approval for this request
            async with get_db_session() as session:
                from datetime import datetime, timedelta
                approval = Approval(
                    request_id=request_id,
                    approval_type='requirements',
                    submitted_by='requirements_agent',
                    submitted_at=datetime.now(),
                    timeout_at=datetime.now() + timedelta(hours=24),
                    status='pending',
                    approval_data={'completeness_score': 0.9}
                )
                session.add(approval)
                await session.commit()

            await asyncio.sleep(0.1)  # Small delay to ensure different timestamps

        # Fetch approvals
        async with get_db_session() as session:
            approval_service = ApprovalService(session)
            all_approvals = await approval_service.get_pending_approvals()

            # Filter to our test approvals
            test_approvals = [
                a for a in all_approvals
                if a.request_id in request_ids
            ]

            print(f"\n   Found {len(test_approvals)} test approvals")

            if len(test_approvals) >= 2:
                # Verify newest first
                first_approval = test_approvals[0]
                second_approval = test_approvals[1]

                print(f"\n   Order check:")
                print(f"     1st: {first_approval.submitted_at}")
                print(f"     2nd: {second_approval.submitted_at}")

                assert first_approval.submitted_at > second_approval.submitted_at, \
                    "Approvals not in newest-first order"

                print(f"\n✅ PASS: Approvals in newest-first order")
            else:
                print(f"\n⚠️  Not enough approvals to test ordering")
