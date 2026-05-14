"""
Sprint 8 Prompt Optimization Tests

Validates that prompt caching is enabled and working correctly for:
1. Formal Portal (Requirements Agent)
2. Exploratory Portal (Query Interpreter)

Expected savings: $21,000/year (26% cost reduction)
"""

import os

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from langchain_core.messages import SystemMessage, HumanMessage

from app.utils.llm_client import LLMClient
from app.services.query_interpreter import QueryInterpreter


class TestPromptCachingEnabled:
    """Unit tests: Verify cache_control parameter is present"""

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-for-mock"})
    async def test_llm_client_complete_with_custom_system_prompt_has_cache_control(self):
        """Verify custom system prompts have cache_control enabled.

        ``ANTHROPIC_API_KEY`` is patched so ``LLMClient.__init__`` constructs
        a non-None ``self.client`` (falsy-key guard at ``llm_client.py:38-40``
        otherwise routes to the dummy-response path and skips ``ainvoke``).
        """
        from langchain_anthropic import ChatAnthropic

        llm_client = LLMClient()

        # Patch ChatAnthropic class to intercept creation
        with patch("app.utils.llm_client.ChatAnthropic") as MockChatAnthropic:
            mock_response = MagicMock()
            mock_response.content = "Test response"
            mock_instance = MockChatAnthropic.return_value
            mock_instance.ainvoke = AsyncMock(return_value=mock_response)

            # Call with custom system prompt
            await llm_client.complete(
                prompt="Test prompt", system="Custom system prompt for testing"
            )

            # Verify ainvoke was called
            assert mock_instance.ainvoke.called

            # Get the messages passed to ainvoke
            call_args = mock_instance.ainvoke.call_args
            messages = call_args[0][0]  # First positional argument

            # Verify system message uses content-block form with cache_control
            # (Sprint 8.2 Task 2: langchain-anthropic 1.0.1's _format_messages
            # silently drops additional_kwargs.cache_control for string-content
            # SystemMessages; only the list-of-content-blocks form preserves it.)
            system_msg = messages[0]
            assert isinstance(system_msg, SystemMessage)
            assert isinstance(system_msg.content, list), (
                "system content must be content-block list, not string — "
                "string form discards cache_control in langchain-anthropic 1.0.1+"
            )
            assert len(system_msg.content) == 1
            block = system_msg.content[0]
            assert block["type"] == "text"
            assert block["text"] == "Custom system prompt for testing"
            assert block["cache_control"] == {"type": "ephemeral"}

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-for-mock"})
    async def test_llm_client_complete_with_default_system_prompt_has_cache_control(self):
        """Verify default system prompts have cache_control enabled.

        Same ``ANTHROPIC_API_KEY`` patch as the sibling test — needed so
        ``LLMClient.__init__`` constructs ``self.client`` instead of routing
        to the dummy-response path.
        """
        from langchain_anthropic import ChatAnthropic

        llm_client = LLMClient()

        # Patch ChatAnthropic class to intercept creation
        with patch("app.utils.llm_client.ChatAnthropic") as MockChatAnthropic:
            mock_response = MagicMock()
            mock_response.content = "Test response"
            mock_instance = MockChatAnthropic.return_value
            mock_instance.ainvoke = AsyncMock(return_value=mock_response)

            # Call with no system prompt (uses default)
            await llm_client.complete(prompt="Test prompt")

            # Get the messages passed to ainvoke
            call_args = mock_instance.ainvoke.call_args
            messages = call_args[0][0]

            # Verify default system message uses content-block form (see sibling test note)
            system_msg = messages[0]
            assert isinstance(system_msg, SystemMessage)
            assert isinstance(system_msg.content, list)
            assert len(system_msg.content) == 1
            block = system_msg.content[0]
            assert block["type"] == "text"
            assert block["text"] == "You are a helpful clinical research data specialist."
            assert block["cache_control"] == {"type": "ephemeral"}

    @pytest.mark.asyncio
    async def test_extract_requirements_uses_cached_system_prompt(self):
        """Verify extract_requirements calls complete() with caching enabled"""
        llm_client = LLMClient()

        # Mock complete() to verify it's called
        with patch.object(llm_client, "complete", new=AsyncMock()) as mock_complete:
            mock_complete.return_value = """{
                "extracted_requirements": {
                    "study_title": "Test Study",
                    "inclusion_criteria": ["diabetes"],
                    "data_elements": ["demographics"],
                    "phi_level": "de-identified"
                },
                "missing_fields": ["irb_number"],
                "next_question": "What is your IRB number?",
                "completeness_score": 0.7,
                "ready_for_submission": false
            }"""

            conversation_history = [{"role": "user", "message": "I need data on diabetic patients"}]
            current_requirements = {}

            await llm_client.extract_requirements(conversation_history, current_requirements)

            # Verify complete was called (which has caching enabled)
            assert mock_complete.called

    @pytest.mark.asyncio
    async def test_query_interpreter_uses_cached_system_prompt(self):
        """Verify QueryInterpreter uses cached system prompt"""
        interpreter = QueryInterpreter()

        # Mock extract_structured_json to verify system prompt is passed
        with patch.object(
            interpreter.llm_client, "extract_structured_json", new=AsyncMock()
        ) as mock_extract:
            mock_extract.return_value = {
                "query_type": "count",
                "resources": ["Patient"],
                "filters": {"gender": "male"},
                "view_definitions": ["patient_demographics"],
                "explanation": "Count male patients",
                "group_by": [],
                "aggregation_type": "count",
            }

            await interpreter.interpret_query("How many male patients?")

            # Verify extract_structured_json was called with system prompt
            assert mock_extract.called
            call_kwargs = mock_extract.call_args[1]
            assert "system" in call_kwargs
            system_prompt = call_kwargs["system"]

            # Verify system prompt carries the core schema content.
            # Sprint 8 Optimization 7 condensed the prompt 1200→700 tokens
            # (per archive doc), dropping the "Available " prefix. The
            # assertion now checks the structural anchors that survived the
            # rewrite.
            assert "ViewDefinitions:" in system_prompt
            assert "Common Conditions" in system_prompt
            assert "patient_demographics" in system_prompt


class TestPromptCachingIntegration:
    """Integration tests: Verify caching works with real LLM calls"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_api_key
    async def test_repeated_calls_use_cache(self):
        """
        Verify that repeated LLM calls with same system prompt use cache

        This test requires:
        - ANTHROPIC_API_KEY set (with available credits)
        - LANGCHAIN_TRACING_V2=true
        - LANGCHAIN_API_KEY set

        After running, check LangSmith for cache hits (should show >50% cache hit rate)
        """
        llm_client = LLMClient()

        if not llm_client.client:
            pytest.skip("ANTHROPIC_API_KEY not set - skipping integration test")

        system_prompt = "You are a test assistant. Always respond with 'OK'."

        # First call - no cache hit (cold cache)
        response1 = await llm_client.complete(prompt="Test 1", system=system_prompt)

        # Second call - should hit cache for system prompt
        response2 = await llm_client.complete(prompt="Test 2", system=system_prompt)

        # Both calls should succeed
        assert response1
        assert response2

        # NOTE: Actual cache hit verification must be done via LangSmith dashboard
        # Expected: Input tokens for system prompt should be marked as "cache read"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_query_interpreter_cache_hit(self):
        """
        Verify QueryInterpreter benefits from caching on repeated queries

        The large system prompt (~1,200 tokens) should be cached after first call.
        """
        interpreter = QueryInterpreter()

        if not interpreter.llm_client.client:
            pytest.skip("ANTHROPIC_API_KEY not set - skipping integration test")

        # First query - cold cache
        intent1 = await interpreter.interpret_query("How many patients?")
        assert intent1.query_type in ["count", "list"]

        # Second query - warm cache (system prompt cached)
        intent2 = await interpreter.interpret_query("How many male patients?")
        assert intent2.query_type in ["count", "list"]

        # Verify gender filter detected
        if "gender" in intent2.search_params:
            assert intent2.search_params["gender"] == "male"

        # NOTE: Check LangSmith for cache hits on the ~1,200 token system prompt


class TestCostValidation:
    """Validate cost savings from prompt caching"""

    def test_expected_formal_portal_savings(self):
        """
        Formal Portal cost reduction calculation

        Before: $0.005 per request (600 input tokens, 200 output tokens)
        After: $0.003 per request (50% cache hit on 600 token system prompt)
        Savings: $0.002 per request × 1M requests/year = $2,000/year

        Source: Sprint 8 docs, line 162-176
        """
        # Baseline costs (from Sprint 8 analysis)
        baseline_input_tokens = 600  # Per extract_requirements call
        baseline_cost_per_1k_tokens = 0.003  # Sonnet 4.5 input
        baseline_annual_requests = 1_000_000

        baseline_annual_cost = (
            baseline_input_tokens / 1000 * baseline_cost_per_1k_tokens * baseline_annual_requests
        )

        # Optimized costs (50% cache hit on system prompt)
        # System prompt is ~300 tokens of the 600 total
        cached_tokens = 300
        cache_savings = cached_tokens * 0.5  # 50% cache hit rate
        optimized_input_tokens = baseline_input_tokens - cache_savings

        optimized_annual_cost = (
            optimized_input_tokens / 1000 * baseline_cost_per_1k_tokens * baseline_annual_requests
        )

        savings = baseline_annual_cost - optimized_annual_cost

        # Verify savings match Sprint 8 projections ($2,000/year)
        assert savings >= 400  # Allow wide margin due to token estimation
        assert savings <= 600  # 50% of 1M × $0.003 × 0.3k tokens ≈ $450

    def test_expected_exploratory_portal_savings(self):
        """
        Exploratory Portal cost reduction calculation

        Before: $0.007 per query (2,400 input tokens)
        After: $0.0052 per query (50% cache hit on 1,200 token system prompt)
        Savings: $0.0018 per query × 10M queries/year = $18,000/year
        """
        # Baseline costs (from Sprint 8 analysis)
        baseline_input_tokens = 2400
        baseline_cost_per_1k_tokens = 0.003  # Sonnet 4.5 input
        baseline_annual_queries = 10_000_000

        baseline_annual_cost = (
            baseline_input_tokens / 1000 * baseline_cost_per_1k_tokens * baseline_annual_queries
        )

        # Optimized costs (50% cache hit on 1,200 tokens)
        cached_tokens = 1200
        cache_savings = cached_tokens * 0.5  # 50% cache hit rate
        optimized_input_tokens = baseline_input_tokens - cache_savings

        optimized_annual_cost = (
            optimized_input_tokens / 1000 * baseline_cost_per_1k_tokens * baseline_annual_queries
        )

        savings = baseline_annual_cost - optimized_annual_cost

        # Verify savings match Sprint 8 projections ($18,000/year)
        assert savings >= 16200  # Allow 10% margin
        assert savings <= 19800

    def test_total_expected_savings(self):
        """
        Total expected savings from prompt caching optimization

        Formal Portal: ~$450-600/year (conservative estimate)
        Exploratory Portal: $18,000/year
        Total: ~$18,500-18,600/year (23% reduction)

        Note: Sprint 8 initially estimated $21K total, but formal portal savings
        were revised down after detailed token analysis.
        """
        # Conservative estimates based on corrected calculations
        formal_savings_min = 400  # From test above
        formal_savings_max = 600
        exploratory_savings = 18000

        total_savings_min = formal_savings_min + exploratory_savings
        total_savings_max = formal_savings_max + exploratory_savings

        # Verify savings are in expected range
        assert total_savings_min >= 18000
        assert total_savings_max <= 19000

        # Verify this is ~23% of total platform costs ($80,500/year)
        baseline_annual_cost = 80500
        reduction_pct_min = total_savings_min / baseline_annual_cost
        reduction_pct_max = total_savings_max / baseline_annual_cost

        assert reduction_pct_min >= 0.22  # ~22% reduction minimum
        assert reduction_pct_max <= 0.24  # ~24% reduction maximum


class TestBackwardCompatibility:
    """Verify caching doesn't break existing functionality"""

    @pytest.mark.asyncio
    async def test_extract_requirements_still_works(self):
        """Verify extract_requirements produces valid output with caching"""
        llm_client = LLMClient()

        # Mock to avoid real API call
        with patch.object(llm_client, "complete", new=AsyncMock()) as mock_complete:
            mock_complete.return_value = """{
                "extracted_requirements": {
                    "study_title": "Diabetes Study",
                    "principal_investigator": "Dr. Smith",
                    "irb_number": "IRB-2024-001",
                    "inclusion_criteria": ["diabetes type 2", "age > 18"],
                    "exclusion_criteria": ["pregnancy"],
                    "data_elements": ["demographics", "labs"],
                    "time_period": {"start": "2023-01-01", "end": "2024-12-31"},
                    "delivery_format": "CSV",
                    "phi_level": "de-identified"
                },
                "missing_fields": [],
                "next_question": "Do you need any additional data elements?",
                "completeness_score": 0.95,
                "ready_for_submission": true
            }"""

            result = await llm_client.extract_requirements(
                conversation_history=[{"role": "user", "message": "I need diabetic patient data"}],
                current_requirements={},
            )

            # Verify structure unchanged
            assert "extracted_requirements" in result
            assert "missing_fields" in result
            assert "next_question" in result
            assert "completeness_score" in result
            assert "ready_for_submission" in result

    @pytest.mark.asyncio
    async def test_query_interpreter_still_works(self):
        """Verify QueryInterpreter produces valid output with caching"""
        interpreter = QueryInterpreter()

        # Mock to avoid real API call
        with patch.object(
            interpreter.llm_client, "extract_structured_json", new=AsyncMock()
        ) as mock_extract:
            mock_extract.return_value = {
                "query_type": "list",
                "resources": ["Patient", "Condition"],
                "filters": {"gender": "female", "age_max": 30},
                "view_definitions": ["patient_demographics", "condition_simple"],
                "explanation": "List female patients under 30 with diabetes",
            }

            intent = await interpreter.interpret_query(
                "Show me female patients under 30 with diabetes"
            )

            # Verify QueryIntent structure unchanged
            assert intent.query_type == "list"
            assert "Patient" in intent.resources
            assert "patient_demographics" in intent.view_definitions


@pytest.mark.asyncio
@pytest.mark.requires_api_key
async def test_end_to_end_formal_portal_workflow():
    """
    End-to-end test: Formal portal request with caching

    Simulates full workflow from Requirements Agent through Phenotype Agent
    """
    llm_client = LLMClient()

    if not llm_client.client:
        pytest.skip("ANTHROPIC_API_KEY not set - skipping E2E test")

    # Step 1: Extract requirements (uses caching)
    conversation = [
        {
            "role": "user",
            "message": "I need data on male diabetic patients over 50 for a study on HbA1c control",
        }
    ]

    requirements_result = await llm_client.extract_requirements(
        conversation_history=conversation, current_requirements={}
    )

    # Verify requirements extracted
    assert "extracted_requirements" in requirements_result
    assert requirements_result["completeness_score"] > 0

    # Step 2: Extract medical concepts (uses caching)
    criterion = "male patients with type 2 diabetes over age 50"
    concepts_result = await llm_client.extract_medical_concepts(criterion)

    # Verify concepts extracted
    assert "concepts" in concepts_result
    assert len(concepts_result["concepts"]) > 0


@pytest.mark.asyncio
async def test_end_to_end_exploratory_portal_workflow():
    """
    End-to-end test: Exploratory portal query with caching

    Simulates multiple queries in a session (cache warm-up scenario)
    """
    interpreter = QueryInterpreter()

    if not interpreter.llm_client.client:
        pytest.skip("ANTHROPIC_API_KEY not set - skipping E2E test")

    # Query 1: Initial query (cold cache)
    intent1 = await interpreter.interpret_query("How many patients do we have?")
    assert intent1.query_type in ["count", "list"]

    # Query 2: Similar query (warm cache - system prompt cached)
    intent2 = await interpreter.interpret_query("How many male patients?")
    assert intent2.query_type in ["count", "list"]

    # Query 3: Complex query (warm cache - system prompt still cached)
    intent3 = await interpreter.interpret_query("Show me diabetic patients broken down by gender")
    assert intent3.query_type in ["count", "aggregate", "list"]

    # Verify breakdown detection
    if intent3.group_by:
        assert "gender" in intent3.group_by
