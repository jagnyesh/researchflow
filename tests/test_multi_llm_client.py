"""
Tests for MultiLLMClient

Tests multi-provider LLM routing, fallback behavior, and integration with agents.
"""

import pytest
import os
from unittest.mock import Mock, AsyncMock, patch
from app.utils.multi_llm_client import MultiLLMClient, CRITICAL_TASK_TYPES, NON_CRITICAL_TASK_TYPES


class TestMultiLLMClientInitialization:
    """Test MultiLLMClient initialization with different configurations"""

    def test_init_with_anthropic_only(self):
        """Test initialization with Anthropic as only provider"""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key', 'SECONDARY_LLM_PROVIDER': 'anthropic'}):
            client = MultiLLMClient()
            assert client.secondary_provider == 'anthropic'
            assert client.aisuite_client is None
            assert client.claude_client is not None

    @patch('app.utils.multi_llm_client.aisuite')
    def test_init_with_openai(self, mock_aisuite):
        """Test initialization with OpenAI as secondary provider"""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-anthropic-key',
            'SECONDARY_LLM_PROVIDER': 'openai',
            'OPENAI_API_KEY': 'test-openai-key'
        }):
            client = MultiLLMClient()
            assert client.secondary_provider == 'openai'
            mock_aisuite.Client.assert_called_once()

    @patch('app.utils.multi_llm_client.aisuite')
    def test_init_with_ollama(self, mock_aisuite):
        """Test initialization with Ollama as secondary provider"""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'SECONDARY_LLM_PROVIDER': 'ollama',
            'OLLAMA_BASE_URL': 'http://localhost:11434'
        }):
            client = MultiLLMClient()
            assert client.secondary_provider == 'ollama'

    def test_init_openai_without_api_key(self):
        """Test that OpenAI config without API key falls back to Anthropic"""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'SECONDARY_LLM_PROVIDER': 'openai'
        }, clear=True):
            # Remove OPENAI_API_KEY if it exists
            os.environ.pop('OPENAI_API_KEY', None)
            client = MultiLLMClient()
            assert client.secondary_provider == 'anthropic'

    def test_fallback_enabled_by_default(self):
        """Test that fallback is enabled by default"""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            client = MultiLLMClient()
            assert client.enable_fallback is True

    def test_fallback_can_be_disabled(self):
        """Test that fallback can be disabled via env var"""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'ENABLE_LLM_FALLBACK': 'false'
        }):
            client = MultiLLMClient(enable_fallback=True)
            assert client.enable_fallback is False


class TestModelIdentifierSelection:
    """Test model identifier selection based on task type"""

    def test_critical_tasks_use_claude(self):
        """Test that critical tasks always use Claude"""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'SECONDARY_LLM_PROVIDER': 'openai'
        }):
            client = MultiLLMClient()
            for task_type in CRITICAL_TASK_TYPES:
                model_id = client._get_model_identifier(task_type)
                assert model_id.startswith('anthropic:')

    @patch('app.utils.multi_llm_client.aisuite')
    def test_non_critical_tasks_use_secondary_provider(self, mock_aisuite):
        """Test that non-critical tasks use secondary provider when configured"""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'SECONDARY_LLM_PROVIDER': 'openai',
            'OPENAI_API_KEY': 'test-openai-key',
            'SECONDARY_LLM_MODEL': 'gpt-4o'
        }):
            client = MultiLLMClient()
            model_id = client._get_model_identifier('calendar')
            assert model_id == 'openai:gpt-4o'

    def test_ollama_model_selection(self):
        """Test Ollama model identifier"""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'SECONDARY_LLM_PROVIDER': 'ollama',
            'SECONDARY_LLM_MODEL': 'llama3'
        }):
            with patch('app.utils.multi_llm_client.aisuite'):
                client = MultiLLMClient()
                model_id = client._get_model_identifier('delivery')
                assert model_id == 'ollama:llama3'

    def test_default_model_when_not_specified(self):
        """Test default models when SECONDARY_LLM_MODEL not set"""
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'SECONDARY_LLM_PROVIDER': 'openai',
            'OPENAI_API_KEY': 'test-key'
        }, clear=True):
            os.environ.pop('SECONDARY_LLM_MODEL', None)
            with patch('app.utils.multi_llm_client.aisuite'):
                client = MultiLLMClient()
                model_id = client._get_model_identifier('calendar')
                assert model_id == 'openai:gpt-4o'  # Default OpenAI model


@pytest.mark.asyncio
class TestCompleteMethod:
    """Test the complete() method with different configurations"""

    async def test_critical_task_uses_claude_client(self):
        """Test that critical tasks delegate to Claude client"""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            client = MultiLLMClient()
            client.claude_client.complete = AsyncMock(return_value="Claude response")

            result = await client.complete(
                prompt="Test prompt",
                task_type="requirements"  # Critical task
            )

            assert result == "Claude response"
            client.claude_client.complete.assert_called_once()

    @patch('app.utils.multi_llm_client.aisuite')
    async def test_non_critical_task_uses_secondary_provider(self, mock_aisuite):
        """Test that non-critical tasks use AI Suite when configured"""
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="AI Suite response"))]
        mock_aisuite_instance = Mock()
        mock_aisuite_instance.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_aisuite.Client.return_value = mock_aisuite_instance

        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'SECONDARY_LLM_PROVIDER': 'openai',
            'OPENAI_API_KEY': 'test-openai-key'
        }):
            client = MultiLLMClient()

            result = await client.complete(
                prompt="Test prompt",
                task_type="calendar"  # Non-critical task
            )

            assert result == "AI Suite response"
            mock_aisuite_instance.chat.completions.create.assert_called_once()

    @patch('app.utils.multi_llm_client.aisuite')
    async def test_fallback_to_claude_on_error(self, mock_aisuite):
        """Test automatic fallback to Claude when secondary provider fails"""
        mock_aisuite_instance = Mock()
        mock_aisuite_instance.chat.completions.create = AsyncMock(
            side_effect=Exception("Provider error")
        )
        mock_aisuite.Client.return_value = mock_aisuite_instance

        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'SECONDARY_LLM_PROVIDER': 'openai',
            'OPENAI_API_KEY': 'test-openai-key',
            'ENABLE_LLM_FALLBACK': 'true'
        }):
            client = MultiLLMClient()
            client.claude_client.complete = AsyncMock(return_value="Fallback response")

            result = await client.complete(
                prompt="Test prompt",
                task_type="calendar"
            )

            assert result == "Fallback response"
            client.claude_client.complete.assert_called_once()

    @patch('app.utils.multi_llm_client.aisuite')
    async def test_no_fallback_raises_error(self, mock_aisuite):
        """Test that error is raised when fallback is disabled"""
        mock_aisuite_instance = Mock()
        mock_aisuite_instance.chat.completions.create = AsyncMock(
            side_effect=Exception("Provider error")
        )
        mock_aisuite.Client.return_value = mock_aisuite_instance

        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'SECONDARY_LLM_PROVIDER': 'openai',
            'OPENAI_API_KEY': 'test-openai-key',
            'ENABLE_LLM_FALLBACK': 'false'
        }):
            client = MultiLLMClient(enable_fallback=False)

            with pytest.raises(Exception, match="Provider error"):
                await client.complete(
                    prompt="Test prompt",
                    task_type="calendar"
                )


@pytest.mark.asyncio
class TestExtractStructuredJSON:
    """Test structured JSON extraction"""

    async def test_critical_task_uses_claude_client(self):
        """Test that critical tasks use Claude's extract_structured_json"""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            client = MultiLLMClient()
            client.claude_client.extract_structured_json = AsyncMock(
                return_value={"result": "test"}
            )

            result = await client.extract_structured_json(
                prompt="Extract requirements",
                schema_description="Schema",
                task_type="requirements"
            )

            assert result == {"result": "test"}
            client.claude_client.extract_structured_json.assert_called_once()

    async def test_non_critical_task_json_parsing(self):
        """Test JSON parsing for non-critical tasks"""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            client = MultiLLMClient()
            client.complete = AsyncMock(return_value='{"key": "value"}')

            result = await client.extract_structured_json(
                prompt="Test",
                schema_description="Schema",
                task_type="calendar"
            )

            assert result == {"key": "value"}

    async def test_json_parsing_strips_markdown(self):
        """Test that markdown code blocks are stripped from JSON"""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            client = MultiLLMClient()
            client.complete = AsyncMock(return_value='```json\n{"key": "value"}\n```')

            result = await client.extract_structured_json(
                prompt="Test",
                schema_description="Schema",
                task_type="calendar"
            )

            assert result == {"key": "value"}


@pytest.mark.asyncio
class TestWrapperMethods:
    """Test wrapper methods that delegate to Claude client"""

    async def test_extract_requirements_uses_claude(self):
        """Test that extract_requirements always uses Claude"""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            client = MultiLLMClient()
            client.claude_client.extract_requirements = AsyncMock(
                return_value={"requirements": "test"}
            )

            result = await client.extract_requirements(
                conversation_history=[],
                current_requirements={}
            )

            assert result == {"requirements": "test"}
            client.claude_client.extract_requirements.assert_called_once()

    async def test_extract_medical_concepts_uses_claude(self):
        """Test that extract_medical_concepts always uses Claude"""
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            client = MultiLLMClient()
            client.claude_client.extract_medical_concepts = AsyncMock(
                return_value={"concepts": []}
            )

            result = await client.extract_medical_concepts("diabetes")

            assert result == {"concepts": []}
            client.claude_client.extract_medical_concepts.assert_called_once()


@pytest.mark.asyncio
class TestAgentIntegration:
    """Test integration with Calendar and Delivery agents"""

    async def test_calendar_agent_uses_multi_llm_client(self):
        """Test that Calendar Agent can use MultiLLMClient"""
        from app.agents.calendar_agent import CalendarAgent

        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            agent = CalendarAgent()
            assert agent.llm_client is not None
            assert isinstance(agent.llm_client, MultiLLMClient)

    async def test_delivery_agent_uses_multi_llm_client(self):
        """Test that Delivery Agent can use MultiLLMClient"""
        from app.agents.delivery_agent import DeliveryAgent

        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}):
            agent = DeliveryAgent()
            assert agent.llm_client is not None
            assert isinstance(agent.llm_client, MultiLLMClient)
