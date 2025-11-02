"""
Tests for LangGraph Agent Adapter (Phase 2.1)

Verifies the adapter layer that bridges BaseAgent agents with LangGraph state machine.

Tests:
1. Adapter initialization
2. State-to-context conversion
3. Result-to-state mapping
4. Integration with mock agents
5. Error handling
6. Factory functions
"""

import pytest
from datetime import datetime
from typing import Dict, Any

from app.langchain_orchestrator.agent_adapter import (
    LangGraphAgentAdapter,
    create_adapter_for_agent,
    create_adapters_for_all_agents
)


# ============================================================================
# Mock Agent for Testing
# ============================================================================

class MockBaseAgent:
    """Mock agent that simulates BaseAgent interface"""

    def __init__(self, agent_id="mock_agent"):
        self.agent_id = agent_id
        self.last_task = None
        self.last_context = None

    async def handle_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Mock implementation of BaseAgent.handle_task()"""
        self.last_task = task
        self.last_context = context

        # Return different results based on task
        if task == "validate_feasibility":
            return {
                "feasible": True,
                "feasibility_score": 0.85,
                "cohort_size": 1500,
                "sql": "SELECT * FROM patients WHERE..."
            }
        elif task == "extract_data":
            return {
                "extraction_complete": True,
                "data_summary": {
                    "records_extracted": 1500,
                    "sources": ["Epic", "FHIR"]
                }
            }
        elif task == "validate_extracted_data":
            return {
                "passed": True,
                "overall_status": "passed",
                "qa_report": {
                    "completeness": 0.95,
                    "duplicates": 0
                }
            }
        elif task == "error_task":
            raise Exception("Mock error for testing")
        else:
            return {"status": "unknown_task"}


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_agent():
    """Create mock agent for testing"""
    return MockBaseAgent("test_agent")


@pytest.fixture
def adapter(mock_agent):
    """Create adapter with mock agent"""
    return LangGraphAgentAdapter(mock_agent)


@pytest.fixture
def sample_state() -> Dict[str, Any]:
    """Create sample LangGraph state"""
    return {
        # Request metadata
        "request_id": "TEST-REQ-001",
        "current_state": "feasibility_validation",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),

        # Researcher info
        "researcher_request": "Test research request",
        "researcher_info": {
            "name": "Test Researcher",
            "email": "test@example.com",
            "department": "Research"
        },

        # Requirements
        "requirements": {
            "study_title": "Test Study",
            "inclusion_criteria": ["Age > 18", "Diabetes diagnosis"],
            "exclusion_criteria": ["Pregnant"],
            "data_elements": ["demographics", "lab_results"]
        },
        "requirements_complete": True,
        "completeness_score": 0.9,
        "conversation_history": [],
        "requirements_approved": None,
        "requirements_rejection_reason": None,

        # Feasibility
        "phenotype_sql": None,
        "feasibility_score": 0.0,
        "estimated_cohort_size": None,
        "feasible": False,
        "phenotype_approved": None,
        "phenotype_rejection_reason": None,

        # Kickoff
        "meeting_scheduled": False,
        "meeting_details": None,

        # Extraction
        "extraction_approved": None,
        "extraction_rejection_reason": None,
        "extraction_complete": False,
        "extracted_data_summary": None,

        # QA
        "overall_status": None,
        "qa_report": None,
        "qa_approved": None,
        "qa_rejection_reason": None,

        # Delivery
        "delivered": False,
        "delivered_at": None,
        "delivery_location": None,
        "delivery_info": None,

        # Error handling
        "error": None,
        "escalation_reason": None,

        # Scope change
        "scope_change_requested": False,
        "scope_approved": None
    }


# ============================================================================
# Tests: Adapter Initialization
# ============================================================================

def test_adapter_initialization(mock_agent):
    """Test adapter initializes correctly with agent"""
    adapter = LangGraphAgentAdapter(mock_agent)

    assert adapter.agent == mock_agent
    assert adapter.agent_name == "MockBaseAgent"


def test_adapter_get_agent_info(adapter):
    """Test adapter returns agent metadata"""
    info = adapter.get_agent_info()

    assert info["agent_name"] == "MockBaseAgent"
    assert info["agent_type"] == "MockBaseAgent"
    assert info["has_handle_task"] is True
    assert "agent_module" in info


# ============================================================================
# Tests: State-to-Context Conversion
# ============================================================================

def test_state_to_context_basic(adapter, sample_state):
    """Test basic state-to-context conversion"""
    context = adapter._state_to_context(sample_state)

    # Verify essential fields are mapped
    assert context["request_id"] == "TEST-REQ-001"
    assert context["current_state"] == "feasibility_validation"
    assert context["requirements_complete"] is True
    assert context["requirements"] == sample_state["requirements"]


def test_state_to_context_includes_all_phases(adapter, sample_state):
    """Test that context includes fields from all workflow phases"""
    context = adapter._state_to_context(sample_state)

    # Requirements phase
    assert "requirements" in context
    assert "requirements_complete" in context

    # Feasibility phase
    assert "phenotype_sql" in context
    assert "feasible" in context
    assert "estimated_cohort_size" in context

    # Meeting phase
    assert "meeting_scheduled" in context
    assert "meeting_details" in context

    # Extraction phase
    assert "extraction_complete" in context
    assert "extracted_data_summary" in context

    # Researcher info
    assert "researcher_info" in context
    assert "researcher_request" in context


def test_state_to_context_with_partial_state(adapter):
    """Test context conversion with minimal state"""
    minimal_state = {
        "request_id": "MIN-001",
        "current_state": "new_request"
    }

    context = adapter._state_to_context(minimal_state)

    # Should handle missing fields gracefully
    assert context["request_id"] == "MIN-001"
    assert context["current_state"] == "new_request"
    assert context["requirements"] == {}  # Default empty dict


# ============================================================================
# Tests: Result-to-State Mapping
# ============================================================================

def test_result_to_state_phenotype_agent(adapter):
    """Test mapping phenotype agent results to state"""
    result = {
        "feasible": True,
        "feasibility_score": 0.85,
        "cohort_size": 1500,
        "sql": "SELECT * FROM patients"
    }

    state_updates = adapter._result_to_state(result, "validate_feasibility")

    assert state_updates["feasible"] is True
    assert state_updates["feasibility_score"] == 0.85
    assert state_updates["estimated_cohort_size"] == 1500
    assert state_updates["phenotype_sql"] == "SELECT * FROM patients"
    assert "updated_at" in state_updates


def test_result_to_state_extraction_agent(adapter):
    """Test mapping extraction agent results to state"""
    result = {
        "extraction_complete": True,
        "data_summary": {
            "records": 1500,
            "sources": ["Epic"]
        }
    }

    state_updates = adapter._result_to_state(result, "extract_data")

    assert state_updates["extraction_complete"] is True
    assert state_updates["extracted_data_summary"]["records"] == 1500
    assert "updated_at" in state_updates


def test_result_to_state_qa_agent(adapter):
    """Test mapping QA agent results to state"""
    result = {
        "passed": True,
        "qa_report": {
            "completeness": 0.95,
            "duplicates": 0
        }
    }

    state_updates = adapter._result_to_state(result, "validate_extracted_data")

    assert state_updates["overall_status"] == "passed"
    assert state_updates["qa_report"]["completeness"] == 0.95
    assert "updated_at" in state_updates


def test_result_to_state_delivery_agent(adapter):
    """Test mapping delivery agent results to state"""
    result = {
        "delivered": True,
        "delivery_info": {
            "location": "s3://bucket/data.csv",
            "format": "CSV"
        },
        "delivery_location": "s3://bucket/data.csv"
    }

    state_updates = adapter._result_to_state(result, "deliver_data")

    assert state_updates["delivered"] is True
    assert state_updates["delivery_info"]["location"] == "s3://bucket/data.csv"
    assert state_updates["delivery_location"] == "s3://bucket/data.csv"


def test_result_to_state_with_error(adapter):
    """Test mapping error results to state"""
    result = {
        "error": "Database connection failed"
    }

    state_updates = adapter._result_to_state(result, "any_task")

    assert state_updates["error"] == "Database connection failed"
    assert "updated_at" in state_updates


# ============================================================================
# Tests: Execute with State (Integration)
# ============================================================================

@pytest.mark.asyncio
async def test_execute_with_state_success(adapter, sample_state, mock_agent):
    """Test successful execution with state"""
    state_updates = await adapter.execute_with_state(
        "validate_feasibility",
        sample_state
    )

    # Verify agent was called
    assert mock_agent.last_task == "validate_feasibility"
    assert mock_agent.last_context["request_id"] == "TEST-REQ-001"

    # Verify state updates
    assert state_updates["feasible"] is True
    assert state_updates["feasibility_score"] == 0.85
    assert state_updates["estimated_cohort_size"] == 1500
    assert "updated_at" in state_updates


@pytest.mark.asyncio
async def test_execute_with_state_extraction(adapter, sample_state):
    """Test extraction task execution"""
    state_updates = await adapter.execute_with_state(
        "extract_data",
        sample_state
    )

    assert state_updates["extraction_complete"] is True
    assert state_updates["extracted_data_summary"]["records_extracted"] == 1500


@pytest.mark.asyncio
async def test_execute_with_state_qa(adapter, sample_state):
    """Test QA task execution"""
    state_updates = await adapter.execute_with_state(
        "validate_extracted_data",
        sample_state
    )

    assert state_updates["overall_status"] == "passed"
    assert state_updates["qa_report"]["completeness"] == 0.95


@pytest.mark.asyncio
async def test_execute_with_state_error_handling(adapter, sample_state):
    """Test error handling in execute_with_state"""
    state_updates = await adapter.execute_with_state(
        "error_task",
        sample_state
    )

    # Should return error in state updates, not raise exception
    assert "error" in state_updates
    assert "Mock error" in state_updates["error"]
    assert "updated_at" in state_updates


# ============================================================================
# Tests: Direct Task Execution
# ============================================================================

@pytest.mark.asyncio
async def test_execute_task_passthrough(adapter):
    """Test direct task execution (passthrough to agent)"""
    context = {
        "request_id": "TEST-001",
        "requirements": {}
    }

    result = await adapter.execute_task("validate_feasibility", context)

    # Should return raw agent result, not state updates
    assert result["feasible"] is True
    assert result["feasibility_score"] == 0.85
    # Note: raw result has "cohort_size", not "estimated_cohort_size"
    assert result["cohort_size"] == 1500


# ============================================================================
# Tests: Factory Functions
# ============================================================================

def test_create_adapter_for_agent():
    """Test factory function for single agent"""
    agent = MockBaseAgent("factory_test")
    adapter = create_adapter_for_agent(agent)

    assert isinstance(adapter, LangGraphAgentAdapter)
    assert adapter.agent == agent


def test_create_adapters_for_all_agents():
    """Test factory function for multiple agents"""
    phenotype = MockBaseAgent("phenotype")
    extraction = MockBaseAgent("extraction")
    qa = MockBaseAgent("qa")

    adapters = create_adapters_for_all_agents(
        phenotype_agent=phenotype,
        extraction_agent=extraction,
        qa_agent=qa
    )

    assert len(adapters) == 3
    assert "phenotype" in adapters
    assert "extraction" in adapters
    assert "qa" in adapters

    assert adapters["phenotype"].agent == phenotype
    assert adapters["extraction"].agent == extraction
    assert adapters["qa"].agent == qa


def test_create_adapters_for_all_agents_partial():
    """Test factory with only some agents provided"""
    phenotype = MockBaseAgent("phenotype")

    adapters = create_adapters_for_all_agents(
        phenotype_agent=phenotype
    )

    assert len(adapters) == 1
    assert "phenotype" in adapters
    assert "extraction" not in adapters


# ============================================================================
# Tests: Edge Cases
# ============================================================================

@pytest.mark.asyncio
async def test_adapter_with_empty_result(adapter, sample_state):
    """Test adapter handles empty agent results"""
    # Mock agent that returns empty dict
    class EmptyAgent:
        async def handle_task(self, task, context):
            return {}

    empty_adapter = LangGraphAgentAdapter(EmptyAgent())
    state_updates = await empty_adapter.execute_with_state("test", sample_state)

    # Should at least have updated_at
    assert "updated_at" in state_updates


@pytest.mark.asyncio
async def test_adapter_with_missing_state_fields(adapter):
    """Test adapter handles state with missing fields"""
    incomplete_state = {
        "request_id": "INCOMPLETE-001"
        # Most fields missing
    }

    # Should not raise exception
    state_updates = await adapter.execute_with_state(
        "validate_feasibility",
        incomplete_state
    )

    assert state_updates["feasible"] is True
    assert "updated_at" in state_updates


def test_adapter_state_to_context_preserves_nested_dicts(adapter):
    """Test that nested dict structures are preserved in context"""
    state = {
        "request_id": "NESTED-001",
        "requirements": {
            "study_title": "Nested Test",
            "nested_data": {
                "level1": {
                    "level2": "value"
                }
            }
        }
    }

    context = adapter._state_to_context(state)

    assert context["requirements"]["nested_data"]["level1"]["level2"] == "value"


# ============================================================================
# Tests: Alternate Result Formats
# ============================================================================

def test_result_to_state_cohort_size_vs_estimated_cohort_size(adapter):
    """Test adapter handles both cohort_size and estimated_cohort_size"""
    # Agent returns "cohort_size" (common variant)
    result = {"cohort_size": 2000}
    state_updates = adapter._result_to_state(result, "validate_feasibility")
    assert state_updates["estimated_cohort_size"] == 2000

    # Agent returns "estimated_cohort_size" (preferred)
    result = {"estimated_cohort_size": 3000}
    state_updates = adapter._result_to_state(result, "validate_feasibility")
    assert state_updates["estimated_cohort_size"] == 3000


def test_result_to_state_sql_vs_phenotype_sql(adapter):
    """Test adapter handles both sql and phenotype_sql"""
    # Agent returns "sql" (common variant)
    result = {"sql": "SELECT ..."}
    state_updates = adapter._result_to_state(result, "validate_feasibility")
    assert state_updates["phenotype_sql"] == "SELECT ..."

    # Agent returns "phenotype_sql" (preferred)
    result = {"phenotype_sql": "SELECT ..."}
    state_updates = adapter._result_to_state(result, "validate_feasibility")
    assert state_updates["phenotype_sql"] == "SELECT ..."


def test_result_to_state_data_summary_vs_extracted_data_summary(adapter):
    """Test adapter handles both data_summary and extracted_data_summary"""
    # Agent returns "data_summary" (common variant)
    result = {"data_summary": {"records": 100}}
    state_updates = adapter._result_to_state(result, "extract_data")
    assert state_updates["extracted_data_summary"]["records"] == 100

    # Agent returns "extracted_data_summary" (preferred)
    result = {"extracted_data_summary": {"records": 200}}
    state_updates = adapter._result_to_state(result, "extract_data")
    assert state_updates["extracted_data_summary"]["records"] == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
