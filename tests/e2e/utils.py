"""
End-to-End Test Utilities

Helper functions for full system integration testing.
"""

import asyncio
import time
import json
from typing import Dict, Any, Optional
from pathlib import Path
import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database.models import ResearchRequest, RequirementsData, FeasibilityReport, DataDelivery


# ============================================================================
# Configuration
# ============================================================================

class E2EConfig:
    """End-to-end test configuration"""
    API_BASE_URL = "http://localhost:8000"
    API_TIMEOUT = 30.0
    POLL_INTERVAL = 0.5  # seconds
    MAX_WAIT_TIME = 60.0  # seconds
    DATABASE_URL = "postgresql://researchflow:researchflow@localhost:5434/researchflow"


# ============================================================================
# HTTP Client Utilities
# ============================================================================

class APIClient:
    """HTTP client for FastAPI endpoints"""

    def __init__(self, base_url: str = E2EConfig.API_BASE_URL):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=E2EConfig.API_TIMEOUT)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()

    def create_request(self, researcher_info: Dict, initial_request: str) -> Dict[str, Any]:
        """
        Create new research request

        POST /api/requests
        """
        payload = {
            "researcher_info": researcher_info,
            "initial_request": initial_request
        }

        response = self.client.post("/api/requests", json=payload)
        response.raise_for_status()
        return response.json()

    def get_request_status(self, request_id: str) -> Dict[str, Any]:
        """
        Get request status

        GET /api/requests/{request_id}
        """
        response = self.client.get(f"/api/requests/{request_id}")
        response.raise_for_status()
        return response.json()

    def submit_requirements(
        self,
        request_id: str,
        structured_requirements: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Submit structured requirements (shortcut for E2E testing)

        POST /api/requests/{request_id}/requirements
        """
        response = self.client.post(
            f"/api/requests/{request_id}/requirements",
            json={"structured_requirements": structured_requirements}
        )
        response.raise_for_status()
        return response.json()

    def approve_requirements(self, request_id: str, approved: bool = True) -> Dict[str, Any]:
        """
        Approve/reject requirements

        POST /api/approvals/{request_id}/requirements
        """
        response = self.client.post(
            f"/api/approvals/{request_id}/requirements",
            json={"approved": approved, "reviewer": "e2e_test"}
        )
        response.raise_for_status()
        return response.json()

    def approve_phenotype_sql(self, request_id: str, approved: bool = True) -> Dict[str, Any]:
        """
        Approve/reject phenotype SQL

        POST /api/approvals/{request_id}/phenotype
        """
        response = self.client.post(
            f"/api/approvals/{request_id}/phenotype",
            json={"approved": approved, "reviewer": "e2e_test"}
        )
        response.raise_for_status()
        return response.json()

    def approve_extraction(self, request_id: str, approved: bool = True) -> Dict[str, Any]:
        """
        Approve/reject data extraction

        POST /api/approvals/{request_id}/extraction
        """
        response = self.client.post(
            f"/api/approvals/{request_id}/extraction",
            json={"approved": approved, "reviewer": "e2e_test"}
        )
        response.raise_for_status()
        return response.json()

    def approve_qa(self, request_id: str, approved: bool = True) -> Dict[str, Any]:
        """
        Approve/reject QA results

        POST /api/approvals/{request_id}/qa
        """
        response = self.client.post(
            f"/api/approvals/{request_id}/qa",
            json={"approved": approved, "reviewer": "e2e_test"}
        )
        response.raise_for_status()
        return response.json()


# ============================================================================
# Database Utilities
# ============================================================================

class DatabaseHelper:
    """Database utilities for E2E testing"""

    def __init__(self, database_url: str = E2EConfig.DATABASE_URL):
        self.engine = create_engine(database_url)

    def get_request(self, request_id: str) -> Optional[ResearchRequest]:
        """Get research request from database"""
        with Session(self.engine) as session:
            result = session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            return result.scalar_one_or_none()

    def get_requirements(self, request_id: str) -> Optional[RequirementsData]:
        """Get requirements data from database"""
        with Session(self.engine) as session:
            result = session.execute(
                select(RequirementsData).where(RequirementsData.request_id == request_id)
            )
            return result.scalar_one_or_none()

    def get_feasibility_report(self, request_id: str) -> Optional[FeasibilityReport]:
        """Get feasibility report from database"""
        with Session(self.engine) as session:
            result = session.execute(
                select(FeasibilityReport).where(FeasibilityReport.request_id == request_id)
            )
            return result.scalar_one_or_none()

    def get_delivery(self, request_id: str) -> Optional[DataDelivery]:
        """Get delivery data from database"""
        with Session(self.engine) as session:
            result = session.execute(
                select(DataDelivery).where(DataDelivery.request_id == request_id)
            )
            return result.scalar_one_or_none()

    def verify_workflow_state(
        self,
        request_id: str,
        expected_state: str
    ) -> bool:
        """Verify request is in expected workflow state"""
        request = self.get_request(request_id)
        return request and request.current_state == expected_state


# ============================================================================
# Test Data Generators
# ============================================================================

def load_test_fixture(fixture_name: str) -> Dict[str, Any]:
    """Load test fixture from JSON file"""
    fixture_path = Path(__file__).parent / "fixtures" / f"{fixture_name}.json"
    with open(fixture_path, 'r') as f:
        return json.load(f)


def create_test_request_data() -> Dict[str, Any]:
    """Create test request data from fixture"""
    return load_test_fixture("sample_diabetes_request")


# ============================================================================
# Polling Utilities
# ============================================================================

def wait_for_state(
    api_client: APIClient,
    request_id: str,
    target_state: str,
    timeout: float = E2EConfig.MAX_WAIT_TIME
) -> bool:
    """
    Poll request status until it reaches target state or timeout

    Returns:
        True if target state reached, False if timeout
    """
    start_time = time.time()

    while (time.time() - start_time) < timeout:
        status = api_client.get_request_status(request_id)
        current_state = status.get('current_state')

        if current_state == target_state:
            return True

        time.sleep(E2EConfig.POLL_INTERVAL)

    return False


def wait_for_approval_gate(
    api_client: APIClient,
    request_id: str,
    approval_state: str,
    timeout: float = E2EConfig.MAX_WAIT_TIME
) -> bool:
    """
    Wait for workflow to reach an approval gate

    Approval states: requirements_review, phenotype_review, extraction_approval, qa_review

    Returns:
        True if approval gate reached, False if timeout
    """
    return wait_for_state(api_client, request_id, approval_state, timeout)


# ============================================================================
# Assertion Utilities
# ============================================================================

def assert_workflow_complete(
    db_helper: DatabaseHelper,
    request_id: str
):
    """Assert that workflow completed successfully"""
    request = db_helper.get_request(request_id)

    assert request is not None, f"Request {request_id} not found in database"
    assert request.current_state == "complete", f"Expected state 'complete', got '{request.current_state}'"
    assert request.final_state == "complete", f"Expected final_state 'complete', got '{request.final_state}'"

    # Verify all required data exists
    requirements = db_helper.get_requirements(request_id)
    assert requirements is not None, "Requirements data not found"
    assert requirements.is_complete == True, "Requirements not marked as complete"

    feasibility = db_helper.get_feasibility_report(request_id)
    assert feasibility is not None, "Feasibility report not found"
    assert feasibility.is_feasible == True, "Feasibility not marked as feasible"

    delivery = db_helper.get_delivery(request_id)
    assert delivery is not None, "Delivery data not found"
    assert delivery.delivered_at is not None, "Delivery timestamp not set"


def assert_agents_executed(
    db_helper: DatabaseHelper,
    request_id: str,
    expected_agents: list
):
    """Assert that all expected agents executed"""
    request = db_helper.get_request(request_id)

    assert request is not None, f"Request {request_id} not found"

    agents_involved = request.agents_involved or []

    for agent_id in expected_agents:
        assert any(
            execution.get('agent_id') == agent_id for execution in agents_involved
        ), f"Agent '{agent_id}' did not execute"


def assert_sql_generated(
    db_helper: DatabaseHelper,
    request_id: str
):
    """Assert that phenotype SQL was generated"""
    feasibility = db_helper.get_feasibility_report(request_id)

    assert feasibility is not None, "Feasibility report not found"
    assert feasibility.phenotype_sql is not None, "Phenotype SQL not generated"
    assert len(feasibility.phenotype_sql) > 0, "Phenotype SQL is empty"
    assert "SELECT" in feasibility.phenotype_sql.upper(), "Invalid SQL (missing SELECT)"
