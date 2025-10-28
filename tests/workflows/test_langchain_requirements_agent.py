"""
Tests for LangChain Requirements Agent (Sprint 1)

These tests validate the LangChain-based Requirements Agent implementation
and compare it against the custom implementation.

Test Goals:
1. Feature parity: Same functionality as custom agent
2. Conversation handling: Multi-turn conversations work correctly
3. Requirements extraction: Structured requirements extracted accurately
4. Memory management: Conversation history persisted correctly
5. Error handling: Graceful degradation on failures

Test Coverage:
- Basic conversation flow (single turn)
- Multi-turn conversation (iterative requirements gathering)
- Pre-structured requirements (Research Notebook shortcut)
- Conversation memory (history retention)
- JSON parsing (structured output validation)
- Error handling (malformed responses, API failures)
"""

import pytest
import json
from unittest.mock import Mock, AsyncMock
from datetime import datetime

from app.langchain_orchestrator.langchain_agents import LangChainRequirementsAgent
from tests.fixtures import RequirementsBuilder as RB


@pytest.fixture
def langchain_agent():
    """Create LangChain Requirements Agent instance for testing with mocked LLM"""
    # Create agent
    agent = LangChainRequirementsAgent(
        agent_id="test_langchain_requirements_agent",
        orchestrator=None
    )
    # Replace LLM with a mock that has ainvoke as an AsyncMock
    agent.llm = Mock()
    agent.llm.ainvoke = AsyncMock()
    return agent


@pytest.fixture
def sample_initial_request():
    """Sample initial research request"""
    return "I need patients with diabetes mellitus diagnosed in 2024."


@pytest.fixture
def sample_pre_structured_requirements():
    """Sample pre-structured requirements (from Research Notebook)"""
    return RB.build_requirements(
        inclusion=[
            RB.build_condition('diabetes mellitus', term='diabetes'),
            RB.build_demographic('age > 18', term='age', details='> 18')
        ],
        exclusion=[
            RB.build_condition('pregnancy')
        ],
        time_period={'start': '2024-01-01', 'end': '2024-12-31'},
        data_elements=['demographics', 'lab_results', 'medications'],
        study_title='Diabetes Study 2024',
        principal_investigator='Dr. Smith',
        irb_number='IRB-2024-001',
        phi_level='de-identified'
    )


def set_llm_response(agent, response_data):
    """Helper to set LLM mock response"""
    mock_response = Mock()
    mock_response.content = json.dumps(response_data)
    agent.llm.ainvoke.return_value = mock_response
    return mock_response


class TestBasicConversation:
    """Test basic single-turn conversation"""

    @pytest.mark.asyncio
    async def test_initial_request_processing(self, langchain_agent, sample_initial_request):
        """Test processing initial research request"""

        # Mock LLM response
        set_llm_response(langchain_agent, {
            "extracted_requirements": {
                "inclusion_criteria": [
                    {
                        "description": "diabetes mellitus",
                        "concepts": [{"type": "condition", "term": "diabetes"}],
                        "codes": []
                    }
                ],
                "exclusion_criteria": [],
                "data_elements": [],
                "time_period": {"start": "2024-01-01", "end": "2024-12-31"}
            },
            "completeness_score": 0.4,
            "missing_fields": ["data_elements", "phi_level", "irb_number"],
            "ready_for_submission": False,
            "next_question": "What specific data elements do you need? For example: demographics, lab results, medications?"
        })

        result = await langchain_agent.execute_task(
            task="gather_requirements",
            context={
                "request_id": "test-001",
                "initial_request": sample_initial_request
            }
        )

        # Assertions
        assert result['requirements_complete'] is False
        assert 'next_question' in result
        assert result['completeness_score'] == 0.4
        assert 'diabetes' in str(result['extracted_requirements'])
        assert len(result['missing_fields']) == 3

    @pytest.mark.asyncio
    async def test_conversation_memory_persistence(self, langchain_agent):
        """Test that conversation history is persisted in memory"""

        request_id = "test-002"

        # First turn
        mock_response_1 = Mock()
        mock_response_1.content = json.dumps({
            "extracted_requirements": {"inclusion_criteria": []},
            "completeness_score": 0.2,
            "missing_fields": ["all"],
            "ready_for_submission": False,
            "next_question": "What are your inclusion criteria?"
        })

        langchain_agent.llm.ainvoke.return_value = mock_response_1
        result1 = await langchain_agent.execute_task(
                task="gather_requirements",
                context={
                    "request_id": request_id,
                    "initial_request": "I need diabetes patients"
                }
            )

        # Check memory after first turn
        history = langchain_agent.get_conversation_history(request_id)
        assert len(history) == 2  # User + Assistant
        assert history[0]['role'] == 'user'
        assert history[1]['role'] == 'assistant'

        # Second turn
        mock_response_2 = Mock()
        mock_response_2.content = json.dumps({
            "extracted_requirements": {
                "inclusion_criteria": [
                    {"description": "diabetes", "concepts": [{"type": "condition", "term": "diabetes"}], "codes": []}
                ]
            },
            "completeness_score": 0.5,
            "missing_fields": ["data_elements", "time_period"],
            "ready_for_submission": False,
            "next_question": "What time period?"
        })

        langchain_agent.llm.ainvoke.return_value = mock_response_2
        result2 = await langchain_agent.execute_task(
                task="gather_requirements",
                context={
                    "request_id": request_id,
                    "user_response": "Patients with diabetes mellitus"
                }
            )

        # Check memory after second turn
        history = langchain_agent.get_conversation_history(request_id)
        assert len(history) == 4  # 2 user + 2 assistant messages


class TestMultiTurnConversation:
    """Test multi-turn conversation flow"""

    @pytest.mark.asyncio
    async def test_complete_conversation_flow(self, langchain_agent):
        """Test complete conversation from start to requirements complete"""

        request_id = "test-003"

        # Turn 1: Initial request (incomplete)
        mock_response_1 = Mock()
        mock_response_1.content = json.dumps({
            "extracted_requirements": {
                "inclusion_criteria": [
                    {"description": "diabetes", "concepts": [{"type": "condition", "term": "diabetes"}], "codes": []}
                ],
                "time_period": {"start": "2024-01-01", "end": "2024-12-31"}
            },
            "completeness_score": 0.4,
            "missing_fields": ["data_elements", "phi_level", "irb_number"],
            "ready_for_submission": False,
            "next_question": "What data elements do you need?"
        })

        langchain_agent.llm.ainvoke.return_value = mock_response_1
        result1 = await langchain_agent.execute_task(
                "gather_requirements",
                {
                    "request_id": request_id,
                    "initial_request": "I need diabetes patients from 2024"
                }
            )

        assert result1['requirements_complete'] is False

        # Turn 2: Add data elements (still incomplete)
        mock_response_2 = Mock()
        mock_response_2.content = json.dumps({
            "extracted_requirements": {
                "inclusion_criteria": [
                    {"description": "diabetes", "concepts": [{"type": "condition", "term": "diabetes"}], "codes": []}
                ],
                "time_period": {"start": "2024-01-01", "end": "2024-12-31"},
                "data_elements": ["demographics", "lab_results"]
            },
            "completeness_score": 0.6,
            "missing_fields": ["phi_level", "irb_number"],
            "ready_for_submission": False,
            "next_question": "What PHI level do you need?"
        })

        langchain_agent.llm.ainvoke.return_value = mock_response_2
        result2 = await langchain_agent.execute_task(
                "gather_requirements",
                {
                    "request_id": request_id,
                    "user_response": "I need demographics and lab results"
                }
            )

        assert result2['requirements_complete'] is False
        assert result2['completeness_score'] == 0.6

        # Turn 3: Complete requirements
        mock_response_3 = Mock()
        mock_response_3.content = json.dumps({
            "extracted_requirements": {
                "inclusion_criteria": [
                    {"description": "diabetes", "concepts": [{"type": "condition", "term": "diabetes"}], "codes": []}
                ],
                "time_period": {"start": "2024-01-01", "end": "2024-12-31"},
                "data_elements": ["demographics", "lab_results"],
                "phi_level": "de-identified",
                "study_title": "Diabetes Study",
                "irb_number": "IRB-2024-001"
            },
            "completeness_score": 0.9,
            "missing_fields": [],
            "ready_for_submission": True,
            "next_question": ""
        })

        langchain_agent.llm.ainvoke.return_value = mock_response_3
        result3 = await langchain_agent.execute_task(
                "gather_requirements",
                {
                    "request_id": request_id,
                    "user_response": "De-identified data for IRB-2024-001 Diabetes Study"
                }
            )

        # Verify completion
        assert result3['requirements_complete'] is True
        assert result3['completeness_score'] == 0.9
        assert result3['requires_approval'] is True
        assert result3['approval_type'] == 'requirements'
        assert 'structured_requirements' in result3
        assert result3['structured_requirements']['phi_level'] == 'de-identified'


class TestPreStructuredRequirements:
    """Test pre-structured requirements (Research Notebook shortcut)"""

    @pytest.mark.asyncio
    async def test_pre_structured_requirements_shortcut(
        self,
        langchain_agent,
        sample_pre_structured_requirements
    ):
        """Test that pre-structured requirements skip conversation"""

        result = await langchain_agent.execute_task(
            "gather_requirements",
            {
                "request_id": "test-004",
                "initial_request": "",  # Not needed with pre-structured
                "structured_requirements": sample_pre_structured_requirements,
                "skip_conversation": True
            }
        )

        # Assertions
        assert result['requirements_complete'] is True
        assert result['completeness_score'] == 1.0
        assert result['requires_approval'] is True
        assert result['conversation_history'] == []
        assert result['structured_requirements'] == sample_pre_structured_requirements

    @pytest.mark.asyncio
    async def test_pre_structured_without_skip_flag(
        self,
        langchain_agent,
        sample_pre_structured_requirements
    ):
        """Test that pre-structured requirements without skip_conversation flag are ignored"""

        # Without skip_conversation=True, should start normal conversation
        mock_response = Mock()
        mock_response.content = json.dumps({
            "extracted_requirements": {},
            "completeness_score": 0.1,
            "missing_fields": ["all"],
            "ready_for_submission": False,
            "next_question": "What are your requirements?"
        })

        langchain_agent.llm.ainvoke.return_value = mock_response
        result = await langchain_agent.execute_task(
                "gather_requirements",
                {
                    "request_id": "test-005",
                    "initial_request": "I need diabetes data",
                    "structured_requirements": sample_pre_structured_requirements,
                    "skip_conversation": False  # Explicitly False
                }
            )

        # Should start conversation, not use pre-structured
        assert result['requirements_complete'] is False
        assert 'next_question' in result


class TestConversationMemoryManagement:
    """Test conversation memory management"""

    @pytest.mark.asyncio
    async def test_multiple_requests_isolated_memory(self, langchain_agent):
        """Test that different requests have isolated conversation memory"""

        request_id_1 = "test-006"
        request_id_2 = "test-007"

        mock_response = Mock()
        mock_response.content = json.dumps({
            "extracted_requirements": {},
            "completeness_score": 0.2,
            "missing_fields": ["all"],
            "ready_for_submission": False,
            "next_question": "What do you need?"
        })

        # Process request 1
        langchain_agent.llm.ainvoke.return_value = mock_response
        await langchain_agent.execute_task(
                "gather_requirements",
                {
                    "request_id": request_id_1,
                    "initial_request": "Request 1"
                }
            )

        # Process request 2
        langchain_agent.llm.ainvoke.return_value = mock_response
        await langchain_agent.execute_task(
                "gather_requirements",
                {
                    "request_id": request_id_2,
                    "initial_request": "Request 2"
                }
            )

        # Check that memories are separate
        history_1 = langchain_agent.get_conversation_history(request_id_1)
        history_2 = langchain_agent.get_conversation_history(request_id_2)

        assert len(history_1) == 2  # 1 user + 1 assistant
        assert len(history_2) == 2
        assert history_1[0]['content'] == "Request 1"
        assert history_2[0]['content'] == "Request 2"

    @pytest.mark.asyncio
    async def test_clear_conversation_memory(self, langchain_agent):
        """Test clearing conversation memory for a request"""

        request_id = "test-008"

        mock_response = Mock()
        mock_response.content = json.dumps({
            "extracted_requirements": {},
            "completeness_score": 0.2,
            "missing_fields": ["all"],
            "ready_for_submission": False,
            "next_question": "What do you need?"
        })

        # Add conversation
        langchain_agent.llm.ainvoke.return_value = mock_response
        await langchain_agent.execute_task(
                "gather_requirements",
                {
                    "request_id": request_id,
                    "initial_request": "Test request"
                }
            )

        # Verify memory exists
        history_before = langchain_agent.get_conversation_history(request_id)
        assert len(history_before) > 0

        # Clear memory
        langchain_agent.clear_conversation(request_id)

        # Verify memory cleared
        history_after = langchain_agent.get_conversation_history(request_id)
        assert len(history_after) == 0


class TestJSONParsing:
    """Test JSON parsing and structured output validation"""

    @pytest.mark.asyncio
    async def test_json_in_markdown_code_block(self, langchain_agent):
        """Test parsing JSON from markdown code blocks"""

        mock_response = Mock()
        # LLM sometimes returns JSON in markdown code blocks
        mock_response.content = """Here are the requirements:

```json
{
    "extracted_requirements": {
        "inclusion_criteria": [
            {"description": "diabetes", "concepts": [{"type": "condition", "term": "diabetes"}], "codes": []}
        ]
    },
    "completeness_score": 0.5,
    "missing_fields": ["data_elements"],
    "ready_for_submission": false,
    "next_question": "What data elements?"
}
```

Let me know if you need more details."""

        langchain_agent.llm.ainvoke.return_value = mock_response
        result = await langchain_agent.execute_task(
                "gather_requirements",
                {
                    "request_id": "test-009",
                    "initial_request": "I need diabetes patients"
                }
            )

        # Should successfully parse despite markdown wrapper
        assert result['requirements_complete'] is False
        assert result['completeness_score'] == 0.5

    @pytest.mark.asyncio
    async def test_malformed_json_fallback(self, langchain_agent):
        """Test fallback behavior when JSON parsing fails"""

        mock_response = Mock()
        # Malformed JSON
        mock_response.content = "This is not valid JSON {malformed: true"

        langchain_agent.llm.ainvoke.return_value = mock_response
        result = await langchain_agent.execute_task(
                "gather_requirements",
                {
                    "request_id": "test-010",
                    "initial_request": "I need data"
                }
            )

        # Should fallback gracefully
        assert result['requirements_complete'] is False
        assert 'next_question' in result
        assert result['completeness_score'] == 0.0


class TestErrorHandling:
    """Test error handling and edge cases"""

    @pytest.mark.asyncio
    async def test_llm_api_error_handling(self, langchain_agent):
        """Test handling of LLM API errors"""

        # Mock API error
        langchain_agent.llm.ainvoke.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            await langchain_agent.execute_task(
                "gather_requirements",
                {
                    "request_id": "test-011",
                    "initial_request": "Test request"
                }
            )

    @pytest.mark.asyncio
    async def test_unknown_task_error(self, langchain_agent):
        """Test that unknown tasks raise ValueError"""

        with pytest.raises(ValueError, match="Unknown task"):
            await langchain_agent.execute_task(
                "unknown_task",
                {"request_id": "test-012"}
            )

    @pytest.mark.asyncio
    async def test_empty_conversation_history(self, langchain_agent):
        """Test getting conversation history for non-existent request"""

        history = langchain_agent.get_conversation_history("non-existent-request")
        assert history == []


class TestCompatibilityWithCustomAgent:
    """Test compatibility with custom Requirements Agent interface"""

    @pytest.mark.asyncio
    async def test_execute_task_interface_compatibility(self, langchain_agent):
        """Test that execute_task interface matches custom agent"""

        # Both agents should support these tasks
        tasks = ["gather_requirements", "continue_conversation"]

        mock_response = Mock()
        mock_response.content = json.dumps({
            "extracted_requirements": {},
            "completeness_score": 0.2,
            "missing_fields": ["all"],
            "ready_for_submission": False,
            "next_question": "What do you need?"
        })

        for task in tasks:
            langchain_agent.llm.ainvoke.return_value = mock_response
            result = await langchain_agent.execute_task(
                    task,
                    {
                        "request_id": f"test-{task}",
                        "initial_request": "Test"
                    }
                )

            # Should return expected keys
            assert isinstance(result, dict)
            assert 'requirements_complete' in result or 'next_question' in result

    @pytest.mark.asyncio
    async def test_result_format_compatibility(self, langchain_agent):
        """Test that result format matches custom agent"""

        mock_response = Mock()
        mock_response.content = json.dumps({
            "extracted_requirements": {
                "inclusion_criteria": [],
                "exclusion_criteria": [],
                "data_elements": [],
                "time_period": {},
                "phi_level": "de-identified"
            },
            "completeness_score": 0.9,
            "missing_fields": [],
            "ready_for_submission": True,
            "next_question": ""
        })

        langchain_agent.llm.ainvoke.return_value = mock_response
        result = await langchain_agent.execute_task(
                "gather_requirements",
                {
                    "request_id": "test-013",
                    "initial_request": "Complete request"
                }
            )

        # Expected keys for complete requirements (same as custom agent)
        expected_keys = {
            'requirements_complete',
            'structured_requirements',
            'conversation_history',
            'completeness_score',
            'requires_approval',
            'approval_type',
            'next_agent',
            'next_task',
            'additional_context'
        }

        assert set(result.keys()) == expected_keys
        assert result['requires_approval'] is True
        assert result['approval_type'] == 'requirements'


# Performance benchmarking tests (Sprint 1 goal: compare with custom agent)
class TestPerformanceBenchmarking:
    """Performance benchmarking tests (to be run with benchmarks/compare_requirements_agent.py)"""

    @pytest.mark.asyncio
    async def test_single_turn_latency(self, langchain_agent):
        """Benchmark single conversation turn latency"""

        set_llm_response(langchain_agent, {
            "extracted_requirements": {},
            "completeness_score": 0.2,
            "missing_fields": ["all"],
            "ready_for_submission": False,
            "next_question": "What do you need?"
        })

        # Note: pytest-benchmark doesn't support async by default
        # This is a placeholder - actual benchmarking in benchmarks/compare_requirements_agent.py
        result = await langchain_agent.execute_task(
            "gather_requirements",
            {
                "request_id": "benchmark-001",
                "initial_request": "Test request"
            }
        )
        assert result is not None
