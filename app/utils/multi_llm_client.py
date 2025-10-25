"""
Multi-Provider LLM Client for ResearchFlow

Supports multiple LLM providers via AI Suite with intelligent routing:
- Critical medical tasks (requirements, phenotype) → Always use Claude
- Non-critical tasks (calendar, delivery) → Use configurable secondary provider
- Automatic fallback to Claude if secondary provider fails
"""

import os
import logging
from typing import Dict, Any, Optional, Literal
from .llm_client import LLMClient

logger = logging.getLogger(__name__)

# Task types that are considered critical and must use Claude
CRITICAL_TASK_TYPES = ["requirements", "phenotype", "medical", "sql_generation"]

# Task types that can use secondary providers
NON_CRITICAL_TASK_TYPES = ["calendar", "delivery", "notification", "scheduling"]


class MultiLLMClient:
    """
    Multi-provider LLM client with intelligent routing and fallback

    Routes tasks to appropriate LLM provider based on criticality:
    - Medical/critical tasks always use Claude (proven accuracy)
    - Non-critical tasks use configurable secondary provider
    - Automatic fallback to Claude if secondary provider fails

    Configuration via environment variables:
    - SECONDARY_LLM_PROVIDER: openai, ollama, or anthropic (default)
    - OPENAI_API_KEY: Required if using OpenAI
    - OLLAMA_BASE_URL: Required if using Ollama (default: http://localhost:11434)
    - SECONDARY_LLM_MODEL: Model name for secondary provider
    - ENABLE_LLM_FALLBACK: Enable fallback to Claude (default: true)
    """

    def __init__(
        self,
        anthropic_api_key: Optional[str] = None,
        secondary_provider: Optional[str] = None,
        enable_fallback: bool = True
    ):
        """
        Initialize multi-provider LLM client

        Args:
            anthropic_api_key: Anthropic API key (defaults to env var)
            secondary_provider: Secondary provider (openai, ollama, anthropic)
            enable_fallback: Enable fallback to Claude on errors
        """
        # Always initialize Claude client for critical tasks and fallback
        self.claude_client = LLMClient(api_key=anthropic_api_key)

        # Get configuration
        self.secondary_provider = secondary_provider or os.getenv('SECONDARY_LLM_PROVIDER', 'anthropic')
        self.enable_fallback = enable_fallback and os.getenv('ENABLE_LLM_FALLBACK', 'true').lower() == 'true'
        self.secondary_model = os.getenv('SECONDARY_LLM_MODEL', '')

        # Initialize AI Suite client for secondary provider
        self.aisuite_client = None
        self._init_aisuite()

        logger.info(
            f"MultiLLMClient initialized: secondary_provider={self.secondary_provider}, "
            f"fallback={self.enable_fallback}"
        )

    def _init_aisuite(self):
        """Initialize AI Suite client if secondary provider is configured"""
        if self.secondary_provider == 'anthropic':
            # Use Claude client directly, no need for AI Suite
            logger.info("Secondary provider is Anthropic - using Claude client directly")
            return

        try:
            import aisuite

            # Validate provider configuration
            if self.secondary_provider == 'openai':
                if not os.getenv('OPENAI_API_KEY'):
                    logger.warning("OPENAI_API_KEY not set - falling back to Claude")
                    self.secondary_provider = 'anthropic'
                    return
            elif self.secondary_provider == 'ollama':
                ollama_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
                logger.info(f"Using Ollama at {ollama_url}")

            self.aisuite_client = aisuite.Client()
            logger.info(f"AI Suite initialized for provider: {self.secondary_provider}")

        except ImportError:
            logger.warning("aisuite not installed - falling back to Claude for all tasks")
            self.secondary_provider = 'anthropic'
        except Exception as e:
            logger.error(f"Failed to initialize AI Suite: {str(e)} - falling back to Claude")
            self.secondary_provider = 'anthropic'

    def _get_model_identifier(self, task_type: str) -> str:
        """
        Get model identifier based on task type

        Args:
            task_type: Type of task (requirements, calendar, delivery, etc.)

        Returns:
            Model identifier in format "provider:model-name"
        """
        # Critical tasks always use Claude
        if task_type in CRITICAL_TASK_TYPES:
            return "anthropic:claude-3-5-sonnet-20241022"

        # Non-critical tasks use secondary provider
        if self.secondary_provider == 'anthropic':
            return "anthropic:claude-3-5-sonnet-20241022"
        elif self.secondary_provider == 'openai':
            model = self.secondary_model or "gpt-4o"
            return f"openai:{model}"
        elif self.secondary_provider == 'ollama':
            model = self.secondary_model or "llama3"
            return f"ollama:{model}"
        else:
            logger.warning(f"Unknown provider {self.secondary_provider}, using Claude")
            return "anthropic:claude-3-5-sonnet-20241022"

    async def complete(
        self,
        prompt: str,
        task_type: str = "general",
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system: Optional[str] = None
    ) -> str:
        """
        Get completion from appropriate LLM provider

        Args:
            prompt: User prompt
            task_type: Type of task (determines provider routing)
            model: Override model identifier (optional)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            system: System prompt

        Returns:
            Response text from LLM
        """
        # Determine which provider to use
        use_secondary = (
            task_type in NON_CRITICAL_TASK_TYPES and
            self.secondary_provider != 'anthropic' and
            self.aisuite_client is not None
        )

        # Critical tasks always use Claude client
        if not use_secondary:
            logger.debug(f"Using Claude for task_type={task_type}")
            return await self.claude_client.complete(
                prompt=prompt,
                model=model or "claude-3-5-sonnet-20241022",
                max_tokens=max_tokens,
                temperature=temperature,
                system=system
            )

        # Non-critical tasks use secondary provider with fallback
        model_id = model or self._get_model_identifier(task_type)
        logger.info(f"Using {model_id} for task_type={task_type}")

        try:
            # Use AI Suite for secondary provider
            messages = [{"role": "user", "content": prompt}]
            if system:
                messages.insert(0, {"role": "system", "content": system})

            response = self.aisuite_client.chat.completions.create(
                model=model_id,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            response_text = response.choices[0].message.content
            logger.debug(f"Response from {model_id} ({len(response_text)} chars)")
            return response_text

        except Exception as e:
            logger.error(f"Error with {model_id}: {str(e)}")

            # Fallback to Claude if enabled
            if self.enable_fallback:
                logger.warning(f"Falling back to Claude for task_type={task_type}")
                return await self.claude_client.complete(
                    prompt=prompt,
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system
                )
            else:
                raise

    async def extract_structured_json(
        self,
        prompt: str,
        schema_description: str,
        task_type: str = "general",
        model: Optional[str] = None,
        system: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract structured JSON from text using LLM

        Args:
            prompt: Input text to parse
            schema_description: Description of expected JSON schema
            task_type: Type of task (determines provider routing)
            model: Override model identifier
            system: Optional system prompt

        Returns:
            Parsed JSON object
        """
        # For critical tasks or when secondary is Claude, use Claude client directly
        if task_type in CRITICAL_TASK_TYPES or self.secondary_provider == 'anthropic':
            return await self.claude_client.extract_structured_json(
                prompt=prompt,
                schema_description=schema_description,
                model=model or "claude-3-5-sonnet-20241022",
                system=system
            )

        # For non-critical tasks, use complete() and parse JSON
        full_prompt = f"""{prompt}

{schema_description}

Return ONLY valid JSON, no other text."""

        response = await self.complete(
            prompt=full_prompt,
            task_type=task_type,
            model=model,
            temperature=0.3,
            system=system
        )

        # Parse JSON (same logic as LLMClient)
        import json

        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]

        try:
            return json.loads(response.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM response: {e}")
            logger.debug(f"Response: {response}")
            raise

    # Wrapper methods that delegate to Claude client for backward compatibility

    async def extract_requirements(
        self,
        conversation_history: list,
        current_requirements: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract structured requirements from conversation

        This is a critical medical task, always uses Claude.
        Delegates to LLMClient.extract_requirements()
        """
        logger.debug("Extracting requirements using Claude (critical task)")
        return await self.claude_client.extract_requirements(
            conversation_history=conversation_history,
            current_requirements=current_requirements
        )

    async def extract_medical_concepts(self, criterion: str) -> Dict[str, Any]:
        """
        Extract medical concepts from a clinical criterion

        This is a critical medical task, always uses Claude.
        Delegates to LLMClient.extract_medical_concepts()
        """
        logger.debug("Extracting medical concepts using Claude (critical task)")
        return await self.claude_client.extract_medical_concepts(criterion=criterion)
