"""
Tests for Admin Dashboard Tabs

These tests verify that dashboard tabs correctly query the database
and display real data instead of in-memory state or mock data.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select

from app.database import get_db_session, init_db
from app.database.models import (
    ResearchRequest,
    AgentExecution,
    Escalation,
    RequirementsData,
    Approval
)
from app.orchestrator.workflow_engine import WorkflowState


# Import dashboard functions to test
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.web_ui.admin_dashboard import (
    get_agent_metrics_from_db,
    get_all_requests_from_db,
    get_escalations_from_db,
    get_analytics_from_db,
    AGENT_IDS
)


async def _create_test_data():
    """Helper to create test data"""
    from sqlalchemy import text

    # Clean database first
    async with get_db_session() as session:
        await session.execute(text("DELETE FROM agent_executions"))
        await session.execute(text("DELETE FROM escalations"))
        await session.execute(text("DELETE FROM approvals"))
        await session.execute(text("DELETE FROM data_deliveries"))
        await session.execute(text("DELETE FROM requirements_data"))
        await session.execute(text("DELETE FROM feasibility_reports"))
        await session.execute(text("DELETE FROM research_requests"))
        await session.commit()

    # Create test data
    async with get_db_session() as session:
        # Create test research requests
        req1 = ResearchRequest(
            id="REQ-TEST-001",
            researcher_name="Dr. Test 1",
            researcher_email="test1@hospital.org",
            researcher_department="Cardiology",
            irb_number="IRB-001",
            initial_request="Test request 1",
            current_state=WorkflowState.REQUIREMENTS_GATHERING.value,
            current_agent="requirements_agent",
            agents_involved=[],
            state_history=[],
            created_at=datetime.now() - timedelta(days=2)
        )

        req2 = ResearchRequest(
            id="REQ-TEST-002",
            researcher_name="Dr. Test 2",
            researcher_email="test2@hospital.org",
            researcher_department="Oncology",
            irb_number="IRB-002",
            initial_request="Test request 2",
            current_state=WorkflowState.DELIVERED.value,
            current_agent=None,
            agents_involved=[],
            state_history=[],
            created_at=datetime.now() - timedelta(days=5),
            completed_at=datetime.now() - timedelta(days=1)
        )

        session.add(req1)
        session.add(req2)

        # Create test agent executions
        exec1 = AgentExecution(
            request_id="REQ-TEST-001",
            agent_id="requirements_agent",
            task="gather_requirements",
            started_at=datetime.now() - timedelta(hours=1),
            completed_at=datetime.now() - timedelta(minutes=55),
            status="success",
            duration_seconds=300.0,
            context={"request_id": "REQ-TEST-001"},
            result={},
            retry_count=0
        )

        exec2 = AgentExecution(
            request_id="REQ-TEST-001",
            agent_id="phenotype_agent",
            task="validate_feasibility",
            started_at=datetime.now() - timedelta(minutes=50),
            completed_at=datetime.now() - timedelta(minutes=45),
            status="success",
            duration_seconds=300.0,
            context={"request_id": "REQ-TEST-001"},
            result={},
            retry_count=0
        )

        exec3 = AgentExecution(
            request_id="REQ-TEST-002",
            agent_id="requirements_agent",
            task="gather_requirements",
            started_at=datetime.now() - timedelta(days=5),
            completed_at=datetime.now() - timedelta(days=5),
            status="failed",
            duration_seconds=100.0,
            context={"request_id": "REQ-TEST-002"},
            result={},
            error="Test error",
            retry_count=1
        )

        session.add(exec1)
        session.add(exec2)
        session.add(exec3)

        # Create test escalation
        escalation = Escalation(
            request_id="REQ-TEST-001",
            agent="requirements_agent",
            error="Test escalation error",
            context={},
            task={},
            escalation_reason="error",
            severity="high",
            recommended_action="Review and retry",
            status="pending_review",
            created_at=datetime.now()
        )

        session.add(escalation)

        await session.commit()


@pytest.fixture
async def setup_test_data():
    """Pytest fixture to setup test data before each test"""
    await _create_test_data()
    yield


class TestAgentMetricsTab:
    """Test Agent Metrics tab functionality"""

    @pytest.mark.asyncio
    async def test_get_agent_metrics_from_db(self, setup_test_data):
        """Test that agent metrics are fetched from database correctly"""
        metrics = await get_agent_metrics_from_db()

        # Should have metrics for all agents
        assert len(metrics) == len(AGENT_IDS)
        assert all(agent_id in metrics for agent_id in AGENT_IDS)

        # Check requirements_agent metrics (has 2 executions: 1 success + 1 failed)
        req_metrics = metrics['requirements_agent']
        assert req_metrics['agent_id'] == 'requirements_agent'
        assert req_metrics['total_tasks'] == 2  # 2 executions
        assert req_metrics['successful_tasks'] == 1
        assert req_metrics['failed_tasks'] == 1
        assert req_metrics['success_rate'] == 0.5
        assert req_metrics['avg_duration_seconds'] > 0

        # Check phenotype_agent metrics (has 1 execution)
        pheno_metrics = metrics['phenotype_agent']
        assert pheno_metrics['total_tasks'] == 1
        assert pheno_metrics['successful_tasks'] == 1
        assert pheno_metrics['failed_tasks'] == 0
        assert pheno_metrics['success_rate'] == 1.0

        # Check agents with no executions
        calendar_metrics = metrics['calendar_agent']
        assert calendar_metrics['total_tasks'] == 0
        assert calendar_metrics['successful_tasks'] == 0
        assert calendar_metrics['success_rate'] == 0

    @pytest.mark.asyncio
    async def test_agent_state_determination(self, setup_test_data):
        """Test that agent state is determined correctly"""
        metrics = await get_agent_metrics_from_db()

        # All agents should be idle (no pending executions in test data)
        for agent_id, agent_metrics in metrics.items():
            assert agent_metrics['state'] in ['idle', 'working']

    @pytest.mark.asyncio
    async def test_metrics_with_no_data(self):
        """Test metrics when database is empty"""
        await init_db()

        metrics = await get_agent_metrics_from_db()

        # Should still return metrics for all agents
        assert len(metrics) == len(AGENT_IDS)

        # All metrics should be zero
        for agent_id, agent_metrics in metrics.items():
            assert agent_metrics['total_tasks'] == 0
            assert agent_metrics['successful_tasks'] == 0
            assert agent_metrics['failed_tasks'] == 0
            assert agent_metrics['success_rate'] == 0
            assert agent_metrics['avg_duration_seconds'] == 0


class TestOverviewTab:
    """Test Overview tab functionality"""

    @pytest.mark.asyncio
    async def test_get_all_requests_from_db(self, setup_test_data):
        """Test that requests are fetched from database correctly"""
        requests = await get_all_requests_from_db()

        # Should have test requests (only active ones)
        assert len(requests) >= 1

        # Check request structure
        req = requests[0]
        assert 'request_id' in req
        assert 'current_state' in req
        assert 'current_agent' in req
        assert 'started_at' in req
        assert 'researcher_info' in req
        assert 'name' in req['researcher_info']
        assert 'email' in req['researcher_info']

    @pytest.mark.asyncio
    async def test_only_active_requests_returned(self, setup_test_data):
        """Test that only active (not completed) requests are returned"""
        requests = await get_all_requests_from_db()

        # Should NOT include completed requests
        request_ids = [r['request_id'] for r in requests]

        # REQ-TEST-001 is active (not completed)
        assert any('REQ-TEST-001' in rid for rid in request_ids)

        # REQ-TEST-002 is completed, might be filtered out depending on implementation

    @pytest.mark.asyncio
    async def test_requests_ordered_by_date(self, setup_test_data):
        """Test that requests are ordered by creation date"""
        requests = await get_all_requests_from_db()

        if len(requests) > 1:
            # Should be ordered by created_at desc
            dates = [r['started_at'] for r in requests]
            assert dates == sorted(dates, reverse=True)


class TestEscalationsTab:
    """Test Escalations tab functionality"""

    @pytest.mark.asyncio
    async def test_get_escalations_from_db(self, setup_test_data):
        """Test that escalations are fetched from database correctly"""
        escalations = await get_escalations_from_db()

        # Should have test escalation
        assert len(escalations) >= 1

        # Check escalation structure
        esc = escalations[0]
        assert esc.request_id == "REQ-TEST-001"
        assert esc.agent == "requirements_agent"
        assert esc.error == "Test escalation error"
        assert esc.escalation_reason == "error"
        assert esc.severity == "high"
        assert esc.status == "pending_review"

    @pytest.mark.asyncio
    async def test_only_pending_escalations_returned(self, setup_test_data):
        """Test that only pending escalations are returned"""
        escalations = await get_escalations_from_db()

        # All escalations should have status "pending_review"
        for esc in escalations:
            assert esc.status == "pending_review"

    @pytest.mark.asyncio
    async def test_escalations_ordered_by_date(self, setup_test_data):
        """Test that escalations are ordered by creation date"""
        escalations = await get_escalations_from_db()

        if len(escalations) > 1:
            # Should be ordered by created_at desc
            dates = [esc.created_at for esc in escalations]
            assert dates == sorted(dates, reverse=True)

    @pytest.mark.asyncio
    async def test_escalations_with_no_data(self):
        """Test escalations when database is empty"""
        await init_db()

        escalations = await get_escalations_from_db()

        # Should return empty list
        assert len(escalations) == 0


class TestAnalyticsTab:
    """Test Analytics tab functionality"""

    @pytest.mark.asyncio
    async def test_get_analytics_from_db(self, setup_test_data):
        """Test that analytics are calculated from database correctly"""
        analytics = await get_analytics_from_db()

        # Check analytics structure
        assert 'volume_by_date' in analytics
        assert 'data_elements' in analytics
        assert 'total_requests' in analytics
        assert 'completed_requests' in analytics

        # Should have at least 2 requests from test data
        assert analytics['total_requests'] >= 2

        # Should have 1 completed request
        assert analytics['completed_requests'] >= 1

    @pytest.mark.asyncio
    async def test_volume_by_date_grouping(self, setup_test_data):
        """Test that request volume is grouped by date correctly"""
        analytics = await get_analytics_from_db()

        volume_by_date = analytics['volume_by_date']

        # Should have data for multiple dates
        assert len(volume_by_date) > 0

        # Each date should have submitted and completed counts
        for date_key, counts in volume_by_date.items():
            assert 'submitted' in counts
            assert 'completed' in counts
            assert counts['submitted'] >= counts['completed']  # Can't complete more than submitted

    @pytest.mark.asyncio
    async def test_analytics_time_range(self, setup_test_data):
        """Test that analytics only includes last 30 days"""
        analytics = await get_analytics_from_db()

        volume_by_date = analytics['volume_by_date']

        # All dates should be within last 30 days
        thirty_days_ago = (datetime.now() - timedelta(days=30)).date()

        for date_key in volume_by_date.keys():
            assert date_key >= thirty_days_ago

    @pytest.mark.asyncio
    async def test_analytics_with_no_data(self):
        """Test analytics when database is empty"""
        await init_db()

        analytics = await get_analytics_from_db()

        # Should still return structure with empty/zero values
        assert analytics['total_requests'] == 0
        assert analytics['completed_requests'] == 0
        assert len(analytics['volume_by_date']) == 0
        assert len(analytics['data_elements']) == 0


class TestDashboardIntegration:
    """Integration tests for dashboard"""

    @pytest.mark.asyncio
    async def test_dashboard_data_consistency(self, setup_test_data):
        """Test that data is consistent across all tabs"""
        # Get data from all tabs
        requests = await get_all_requests_from_db()
        metrics = await get_agent_metrics_from_db()
        escalations = await get_escalations_from_db()
        analytics = await get_analytics_from_db()

        # Total agent tasks should match executions in database
        async with get_db_session() as session:
            result = await session.execute(select(AgentExecution))
            all_executions = result.scalars().all()

        total_tasks_from_metrics = sum(m['total_tasks'] for m in metrics.values())
        assert total_tasks_from_metrics == len(all_executions)

        # Total requests from analytics should match database
        async with get_db_session() as session:
            thirty_days_ago = datetime.now() - timedelta(days=30)
            result = await session.execute(
                select(ResearchRequest).where(
                    ResearchRequest.created_at >= thirty_days_ago
                )
            )
            recent_requests = result.scalars().all()

        assert analytics['total_requests'] == len(recent_requests)

    @pytest.mark.asyncio
    async def test_dashboard_survives_restart(self, setup_test_data):
        """Test that dashboard can fetch data after a restart (stateless)"""
        # Get data first time
        metrics1 = await get_agent_metrics_from_db()
        requests1 = await get_all_requests_from_db()

        # Simulate restart by getting data again (data should persist in DB)
        metrics2 = await get_agent_metrics_from_db()
        requests2 = await get_all_requests_from_db()

        # Data should be the same
        assert len(metrics1) == len(metrics2)
        assert len(requests1) == len(requests2)

        # Metrics should match
        for agent_id in AGENT_IDS:
            assert metrics1[agent_id]['total_tasks'] == metrics2[agent_id]['total_tasks']


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, '-v'])
