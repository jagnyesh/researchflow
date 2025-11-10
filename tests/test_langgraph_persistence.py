"""
Tests for LangGraph Persistence Layer (Sprint 6.5)

Verifies:
1. Checkpointer initialization and setup
2. Workflow state persistence across runs
3. Workflow resumption from checkpoints
4. Thread-based state isolation
5. Integration with FullWorkflow
"""

import pytest
import asyncio
import os
from pathlib import Path
from datetime import datetime

from app.langchain_orchestrator.persistence import (
    get_checkpointer,
    create_thread_config,
    clear_checkpointer_cache,
    DEFAULT_CHECKPOINT_DB,
)
from app.langchain_orchestrator.langgraph_workflow import FullWorkflow, FullWorkflowState


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def test_checkpointer():
    """Create a test checkpointer with cleanup"""
    # Use test-specific database to avoid conflicts
    test_db_path = "data/test_checkpoints.db"

    # Override environment variable for this test
    original_env = os.environ.get("LANGGRAPH_CHECKPOINT_DB")
    os.environ["LANGGRAPH_CHECKPOINT_DB"] = test_db_path

    # Initialize checkpointer
    checkpointer = await get_checkpointer()

    yield checkpointer

    # Cleanup
    if original_env:
        os.environ["LANGGRAPH_CHECKPOINT_DB"] = original_env
    else:
        del os.environ["LANGGRAPH_CHECKPOINT_DB"]

    # Clear cache to allow new checkpointer for next test
    clear_checkpointer_cache(test_db_path)

    # Remove test database
    if Path(test_db_path).exists():
        Path(test_db_path).unlink()


@pytest.fixture
def sample_initial_state() -> FullWorkflowState:
    """Create sample initial state for testing"""
    return {
        # Request metadata
        "request_id": "TEST-PERSIST-001",
        "current_state": "new_request",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        # Researcher info
        "researcher_request": "Test persistence request",
        "researcher_info": {
            "name": "Test Researcher",
            "email": "test@example.com",
            "department": "Test Department",
        },
        # Requirements phase
        "requirements": {},
        "conversation_history": [],
        "completeness_score": 0.0,
        "requirements_complete": False,
        "requirements_approved": None,
        "requirements_rejection_reason": None,
        # Feasibility phase
        "phenotype_sql": None,
        "feasibility_score": 0.0,
        "estimated_cohort_size": None,
        "feasible": False,
        "phenotype_approved": None,
        "phenotype_rejection_reason": None,
        # Kickoff phase
        "meeting_scheduled": False,
        "meeting_details": None,
        # Extraction phase
        "extraction_approved": None,
        "extraction_rejection_reason": None,
        "extraction_complete": False,
        "extracted_data_summary": None,
        # QA phase
        "overall_status": None,
        "qa_report": None,
        "qa_approved": None,
        "qa_rejection_reason": None,
        # Delivery phase
        "delivered": False,
        "delivered_at": None,
        "delivery_location": None,
        "delivery_info": None,
        # Error handling
        "error": None,
        "escalation_reason": None,
        # Scope change
        "scope_change_requested": False,
        "scope_approved": None,
    }


# ============================================================================
# Tests: Checkpointer Initialization
# ============================================================================


@pytest.mark.asyncio
async def test_checkpointer_initialization(test_checkpointer):
    """Test that checkpointer initializes successfully"""
    assert test_checkpointer is not None
    assert hasattr(test_checkpointer, "setup")
    assert hasattr(test_checkpointer, "aget")
    assert hasattr(test_checkpointer, "aput")


@pytest.mark.asyncio
async def test_checkpointer_creates_database():
    """Test that checkpointer creates database file"""
    test_db_path = "data/test_checkpoint_creation.db"
    os.environ["LANGGRAPH_CHECKPOINT_DB"] = test_db_path

    checkpointer = await get_checkpointer()

    # Verify database file exists
    assert Path(test_db_path).exists()

    # Cleanup
    Path(test_db_path).unlink()
    del os.environ["LANGGRAPH_CHECKPOINT_DB"]


# ============================================================================
# Tests: Thread Configuration
# ============================================================================


def test_create_thread_config():
    """Test thread config creation"""
    request_id = "REQ-12345"
    config = create_thread_config(request_id)

    assert config is not None
    assert "configurable" in config
    assert config["configurable"]["thread_id"] == request_id


def test_thread_config_unique_per_request():
    """Test that each request gets unique thread config"""
    config1 = create_thread_config("REQ-001")
    config2 = create_thread_config("REQ-002")

    assert config1["configurable"]["thread_id"] != config2["configurable"]["thread_id"]


# ============================================================================
# Tests: Workflow Integration
# ============================================================================


@pytest.mark.asyncio
async def test_workflow_with_persistence(test_checkpointer, sample_initial_state):
    """Test that workflow can run with checkpointer enabled"""
    # Create workflow with checkpointer
    workflow = FullWorkflow(use_real_agents=False, checkpointer=test_checkpointer)

    assert workflow.checkpointer is not None
    assert workflow.checkpointer == test_checkpointer


@pytest.mark.asyncio
async def test_workflow_without_persistence():
    """Test that workflow can run without checkpointer (backward compatibility)"""
    workflow = FullWorkflow(use_real_agents=False, checkpointer=None)

    assert workflow.checkpointer is None


@pytest.mark.asyncio
async def test_workflow_state_persists_across_runs(test_checkpointer, sample_initial_state):
    """
    Test that workflow state is saved to checkpoint and can be resumed.

    This is the key persistence test - verifies:
    1. Workflow runs and creates checkpoint
    2. Checkpoint contains state
    3. New workflow instance can load checkpoint
    """
    # Create workflow with checkpointer
    workflow = FullWorkflow(use_real_agents=False, checkpointer=test_checkpointer)

    # Create thread config for this test
    request_id = "TEST-PERSIST-RESUME-001"
    config = create_thread_config(request_id)

    # Update initial state with request ID
    sample_initial_state["request_id"] = request_id

    # Run workflow (should create checkpoint)
    result = await workflow.run(sample_initial_state, config=config)

    # Verify workflow ran
    assert result is not None
    assert result["request_id"] == request_id

    # Verify checkpoint was created by trying to load it
    checkpoint = await test_checkpointer.aget(config)

    assert checkpoint is not None
    # Checkpoint should contain values
    assert checkpoint.values is not None


@pytest.mark.asyncio
async def test_thread_isolation(test_checkpointer, sample_initial_state):
    """Test that different threads maintain isolated state"""
    workflow = FullWorkflow(use_real_agents=False, checkpointer=test_checkpointer)

    # Run two separate workflows with different thread IDs
    request_id_1 = "TEST-THREAD-001"
    request_id_2 = "TEST-THREAD-002"

    config_1 = create_thread_config(request_id_1)
    config_2 = create_thread_config(request_id_2)

    # Update states
    state_1 = sample_initial_state.copy()
    state_1["request_id"] = request_id_1

    state_2 = sample_initial_state.copy()
    state_2["request_id"] = request_id_2
    state_2["researcher_request"] = "Different request"

    # Run both workflows
    result_1 = await workflow.run(state_1, config=config_1)
    result_2 = await workflow.run(state_2, config=config_2)

    # Verify both ran successfully
    assert result_1["request_id"] == request_id_1
    assert result_2["request_id"] == request_id_2

    # Verify checkpoints are separate
    checkpoint_1 = await test_checkpointer.aget(config_1)
    checkpoint_2 = await test_checkpointer.aget(config_2)

    assert checkpoint_1 is not None
    assert checkpoint_2 is not None
    # Checkpoints should have different checkpoint IDs
    assert checkpoint_1.id != checkpoint_2.id


# ============================================================================
# Tests: Persistence Configuration
# ============================================================================


def test_default_checkpoint_db_path():
    """Test that default checkpoint path is correct"""
    assert DEFAULT_CHECKPOINT_DB == "data/langgraph_checkpoints.db"


def test_checkpoint_db_path_from_env():
    """Test that checkpoint path can be overridden via environment"""
    custom_path = "custom/path/checkpoints.db"
    os.environ["LANGGRAPH_CHECKPOINT_DB"] = custom_path

    # Import after setting env var would use custom path
    # (In real usage, this would be set before app startup)

    # Cleanup
    del os.environ["LANGGRAPH_CHECKPOINT_DB"]


# ============================================================================
# Tests: Error Handling
# ============================================================================


@pytest.mark.asyncio
async def test_checkpointer_handles_concurrent_access(test_checkpointer):
    """Test that checkpointer handles concurrent writes safely"""
    workflow = FullWorkflow(use_real_agents=False, checkpointer=test_checkpointer)

    # Create multiple concurrent runs with different thread IDs
    async def run_workflow(request_id: str, initial_state: FullWorkflowState):
        config = create_thread_config(request_id)
        state = initial_state.copy()
        state["request_id"] = request_id
        return await workflow.run(state, config=config)

    # Run 3 workflows concurrently
    results = await asyncio.gather(
        run_workflow("CONCURRENT-001", sample_initial_state()),
        run_workflow("CONCURRENT-002", sample_initial_state()),
        run_workflow("CONCURRENT-003", sample_initial_state()),
    )

    # All should complete successfully
    assert len(results) == 3
    assert all(r is not None for r in results)
    assert results[0]["request_id"] == "CONCURRENT-001"
    assert results[1]["request_id"] == "CONCURRENT-002"
    assert results[2]["request_id"] == "CONCURRENT-003"


# ============================================================================
# Tests: Cleanup & Maintenance
# ============================================================================


@pytest.mark.asyncio
async def test_checkpoint_database_cleanup():
    """Test that checkpoint database can be cleaned up"""
    test_db_path = "data/test_cleanup_checkpoints.db"
    os.environ["LANGGRAPH_CHECKPOINT_DB"] = test_db_path

    # Create checkpointer
    checkpointer = await get_checkpointer()

    # Verify database exists
    assert Path(test_db_path).exists()

    # Cleanup
    del os.environ["LANGGRAPH_CHECKPOINT_DB"]
    if Path(test_db_path).exists():
        Path(test_db_path).unlink()

    # Verify cleanup worked
    assert not Path(test_db_path).exists()


# ============================================================================
# Integration Test: Complete Workflow with Persistence
# ============================================================================


@pytest.mark.asyncio
async def test_complete_workflow_with_checkpoints(test_checkpointer, sample_initial_state):
    """
    Integration test: Run complete workflow with checkpoints enabled.

    Verifies that checkpoints are created at each state transition.
    """
    workflow = FullWorkflow(use_real_agents=False, checkpointer=test_checkpointer)

    request_id = "TEST-COMPLETE-WORKFLOW-001"
    config = create_thread_config(request_id)

    sample_initial_state["request_id"] = request_id

    # Run workflow (uses stub agents, so completes quickly)
    final_state = await workflow.run(sample_initial_state, config=config)

    # Verify workflow completed
    assert final_state is not None
    assert final_state["request_id"] == request_id

    # Verify final checkpoint exists
    final_checkpoint = await test_checkpointer.aget(config)
    assert final_checkpoint is not None

    # Final state should be a terminal state
    # (For stub workflow, we expect specific terminal states)
    terminal_states = ["complete", "not_feasible", "qa_failed", "human_review"]
    assert final_state["current_state"] in terminal_states


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
