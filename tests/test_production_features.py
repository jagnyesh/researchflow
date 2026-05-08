"""
Test Suite for LangChain Agent Production Features

Tests the production features integrated via LangChainBaseAgentMixin:
1. Retry logic with exponential backoff
2. Database persistence (AgentExecution table)
3. Human escalation workflow
4. State management

Usage:
    pytest tests/test_production_features.py -v -s
"""

import pytest
import asyncio
import time
from datetime import datetime
from typing import Dict, Any
from unittest.mock import AsyncMock

from app.langchain_orchestrator.langchain_agents import LangChainRequirementsAgent
from app.langchain_orchestrator.langchain_base_agent import LangChainBaseAgentMixin, AgentState


class TransientError(Exception):
    """Simulated transient error for retry testing"""

    pass


@pytest.mark.asyncio
async def test_retry_logic_success_after_retry():
    """
    Test that the agent retries on transient errors and eventually succeeds

    Validates:
    - Transient errors trigger retry
    - Exponential backoff is applied (2^retry_count seconds)
    - Task succeeds after retry
    """
    print("\n" + "=" * 80)
    print("TEST: Retry Logic - Success After Retry")
    print("=" * 80)

    agent = LangChainRequirementsAgent()
    attempt_count = 0
    start_time = time.time()

    async def failing_task(context: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal attempt_count
        attempt_count += 1
        print(f"\n  [Attempt {attempt_count}] Task called")

        if attempt_count == 1:
            print(f"  [Attempt {attempt_count}] Raising TransientError (will retry)")
            raise TransientError("Simulated transient failure")

        print(f"  [Attempt {attempt_count}] Success!")
        return {"status": "success", "attempt": attempt_count}

    # Patch should_retry to recognize TransientError
    original_should_retry = agent.should_retry

    def custom_should_retry(error, context):
        if isinstance(error, TransientError):
            return context.get("retry_count", 0) < agent.max_retries
        return original_should_retry(error, context)

    agent.should_retry = custom_should_retry

    # Execute with production features
    context = {"request_id": "TEST-RETRY-001"}
    result = await agent.execute_with_production_features("test_task", context, failing_task)

    elapsed = time.time() - start_time

    print(f"\n  ✓ Total attempts: {attempt_count}")
    print(f"  ✓ Final result: {result}")
    print(f"  ✓ Total time: {elapsed:.2f}s")
    print(f"  ✓ Task history length: {len(agent.task_history)}")

    assert attempt_count == 2, f"Expected 2 attempts, got {attempt_count}"
    assert result["status"] == "success", "Task should have succeeded"
    assert result["attempt"] == 2, "Should have succeeded on attempt 2"
    assert elapsed >= 1.0, f"Should have waited ~1s for retry, but elapsed {elapsed:.2f}s"

    print("\n  ✅ TEST PASSED: Retry logic works correctly")
    print("=" * 80)


@pytest.mark.asyncio
async def test_retry_logic_max_retries_exceeded():
    """
    Test that the agent stops retrying after max_retries is reached

    Validates:
    - Agent retries up to max_retries (3)
    - After max retries, escalation occurs
    """
    print("\n" + "=" * 80)
    print("TEST: Retry Logic - Max Retries Exceeded")
    print("=" * 80)

    agent = LangChainRequirementsAgent()
    attempt_count = 0

    async def always_failing_task(context: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal attempt_count
        attempt_count += 1
        print(f"\n  [Attempt {attempt_count}] Task called (will fail)")
        raise TransientError("Simulated persistent transient failure")

    # Patch should_retry
    original_should_retry = agent.should_retry

    def custom_should_retry(error, context):
        if isinstance(error, TransientError):
            return context.get("retry_count", 0) < agent.max_retries
        return original_should_retry(error, context)

    agent.should_retry = custom_should_retry

    # Mock escalation
    agent.escalate_to_human = AsyncMock()

    # Execute - should fail after max retries
    context = {"request_id": "TEST-RETRY-002"}

    with pytest.raises(TransientError):
        await agent.execute_with_production_features("test_task", context, always_failing_task)

    print(f"\n  ✓ Total attempts: {attempt_count}")
    print(f"  ✓ Escalation called: {agent.escalate_to_human.called}")

    # Should attempt 4 times total: initial + 3 retries
    assert attempt_count == 4, f"Expected 4 attempts (initial + 3 retries), got {attempt_count}"
    assert agent.escalate_to_human.called, "Should have escalated to human after max retries"

    print("\n  ✅ TEST PASSED: Max retries enforced correctly")
    print("=" * 80)


@pytest.mark.asyncio
async def test_state_management():
    """
    Test that agent state transitions correctly during task execution

    Validates:
    - State starts as IDLE
    - Changes to WORKING during task
    - Returns to IDLE after completion
    """
    print("\n" + "=" * 80)
    print("TEST: State Management")
    print("=" * 80)

    agent = LangChainRequirementsAgent()
    states_observed = []

    async def task_with_state_tracking(context: Dict[str, Any]) -> Dict[str, Any]:
        states_observed.append(("during_task", agent.state))
        print(f"  State during task: {agent.state.value}")
        await asyncio.sleep(0.1)
        return {"status": "success"}

    print(f"\n  Initial state: {agent.state.value}")
    assert agent.state == AgentState.IDLE, "Agent should start in IDLE state"
    states_observed.append(("initial", agent.state))

    context = {"request_id": "TEST-STATE-001"}
    await agent.execute_with_production_features("test_task", context, task_with_state_tracking)

    print(f"  Final state: {agent.state.value}")
    assert agent.state == AgentState.IDLE, "Agent should return to IDLE after completion"
    states_observed.append(("final", agent.state))

    print(f"\n  ✓ States observed: {[(label, state.value) for label, state in states_observed]}")
    assert states_observed[0][1] == AgentState.IDLE, "Should start IDLE"
    assert states_observed[1][1] == AgentState.WORKING, "Should be WORKING during task"
    assert states_observed[2][1] == AgentState.IDLE, "Should return to IDLE"

    print("\n  ✅ TEST PASSED: State management works correctly")
    print("=" * 80)


@pytest.mark.asyncio
async def test_task_history_tracking():
    """
    Test that task history is tracked correctly

    Validates:
    - Task execution is recorded in task_history
    - History includes timestamps, status, and results
    """
    print("\n" + "=" * 80)
    print("TEST: Task History Tracking")
    print("=" * 80)

    agent = LangChainRequirementsAgent()

    async def task_1(context):
        await asyncio.sleep(0.1)
        return {"result": "task_1_complete"}

    async def task_2(context):
        await asyncio.sleep(0.1)
        return {"result": "task_2_complete"}

    print("\n  Executing task 1...")
    await agent.execute_with_production_features("task_1", {"request_id": "TEST-HIST-001"}, task_1)

    print("  Executing task 2...")
    await agent.execute_with_production_features("task_2", {"request_id": "TEST-HIST-001"}, task_2)

    history = agent.get_task_history()

    print(f"\n  ✓ Task history length: {len(history)}")
    print(f"  ✓ Task 1 status: {history[0].get('status')}")
    print(f"  ✓ Task 2 status: {history[1].get('status')}")

    assert len(history) == 2, f"Expected 2 tasks in history, got {len(history)}"
    assert history[0]["status"] == "success", "Task 1 should be successful"
    assert history[1]["status"] == "success", "Task 2 should be successful"
    assert "started_at" in history[0], "Task should have started_at timestamp"
    assert "completed_at" in history[0], "Task should have completed_at timestamp"

    print("\n  ✅ TEST PASSED: Task history tracking works correctly")
    print("=" * 80)


@pytest.mark.asyncio
async def test_database_persistence_mock():
    """
    Test that database persistence is attempted (using mocks)

    Validates:
    - _save_execution_to_db is called with correct data
    - AgentExecution record would be created with all fields
    """
    print("\n" + "=" * 80)
    print("TEST: Database Persistence (Mocked)")
    print("=" * 80)

    agent = LangChainRequirementsAgent()
    saved_executions = []

    async def mock_save_execution(task_data):
        saved_executions.append(task_data)
        print(f"\n  Mock save called with:")
        print(f"    - Task: {task_data.get('task')}")
        print(f"    - Status: {task_data.get('status')}")
        print(f"    - Agent ID: {task_data.get('agent_id')}")

    agent._save_execution_to_db = mock_save_execution

    async def test_task(context):
        return {"data": "test_result"}

    context = {"request_id": "TEST-DB-001"}
    await agent.execute_with_production_features("test_task", context, test_task)

    print(f"\n  ✓ Database saves called: {len(saved_executions)}")

    assert len(saved_executions) == 1, "Should have saved 1 execution"

    execution = saved_executions[0]
    assert execution["task"] == "test_task", "Task name should be recorded"
    assert execution["status"] == "success", "Status should be recorded"
    assert execution["agent_id"] == "langchain_requirements_agent", "Agent ID should be recorded"
    assert "started_at" in execution, "Start time should be recorded"
    assert "completed_at" in execution, "Completion time should be recorded"

    print("\n  ✅ TEST PASSED: Database persistence logic works correctly")
    print("=" * 80)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
