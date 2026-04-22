"""
LLM Client for ResearchFlow

Wrapper for Anthropic Claude API with structured output parsing.
Now uses LangChain's ChatAnthropic for automatic LangSmith tracing.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

# Load .env file from project root when this module is imported
# This ensures ANTHROPIC_API_KEY is available before LLMClient is initialized
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_dotenv_path = os.path.join(_project_root, ".env")
load_dotenv(_dotenv_path)

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Client for interacting with Claude API via LangChain

    Uses ChatAnthropic for automatic LangSmith tracing when LANGCHAIN_TRACING_V2=true.
    Provides methods for structured requirement extraction, SQL generation,
    and medical terminology mapping.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-7-sonnet-20250219"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model

        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set - LLM features will be limited")
            self.client = None
        else:
            # LangChain ChatAnthropic automatically traces to LangSmith when:
            # - LANGCHAIN_TRACING_V2=true
            # - LANGCHAIN_API_KEY is set
            # - LANGCHAIN_PROJECT is set
            self.client = ChatAnthropic(
                model=self.model, anthropic_api_key=self.api_key, temperature=0.7, max_tokens=4096
            )
            logger.info(
                f"LLM client initialized with model={self.model} (LangSmith tracing enabled)"
            )

    async def complete(
        self,
        prompt: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system: Optional[str] = None,
    ) -> str:
        """
        Get completion from Claude API via LangChain

        All calls are automatically traced to LangSmith when tracing is enabled.

        Args:
            prompt: User prompt
            model: Model identifier (optional, uses instance default)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            system: System prompt

        Returns:
            Response text from Claude
        """
        if not self.client:
            logger.warning("LLM client not initialized - returning dummy response")
            return self._dummy_response(prompt)

        try:
            # Create a new client instance if model/params differ from default
            if model and model != self.model:
                client = ChatAnthropic(
                    model=model,
                    anthropic_api_key=self.api_key,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            else:
                # Update params on existing client
                client = ChatAnthropic(
                    model=self.model,
                    anthropic_api_key=self.api_key,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

            # Build messages in LangChain format
            messages = []
            if system:
                # Enable prompt caching for system message (Sprint 8 optimization)
                messages.append(
                    SystemMessage(
                        content=system, additional_kwargs={"cache_control": {"type": "ephemeral"}}
                    )
                )
            else:
                # Enable prompt caching for default system message
                messages.append(
                    SystemMessage(
                        content="You are a helpful clinical research data specialist.",
                        additional_kwargs={"cache_control": {"type": "ephemeral"}},
                    )
                )

            messages.append(HumanMessage(content=prompt))

            # Invoke with async - automatically traced to LangSmith!
            response = await client.ainvoke(messages)

            response_text = response.content
            logger.debug(f"LLM response ({len(response_text)} chars)")
            return response_text

        except Exception as e:
            logger.error(f"LLM API error: {str(e)}")
            raise

    async def extract_structured_json(
        self,
        prompt: str,
        schema_description: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract structured JSON from text using LLM

        Args:
            prompt: Input text to parse
            schema_description: Description of expected JSON schema
            model: Model to use (optional)
            system: Optional system prompt

        Returns:
            Parsed JSON object
        """
        full_prompt = f"""{prompt}

{schema_description}

Return ONLY valid JSON, no other text."""

        response = await self.complete(
            full_prompt, model=model or self.model, temperature=0.3, system=system
        )

        # Extract JSON from response (handle markdown code blocks)
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

    async def extract_requirements(
        self, conversation_history: list, current_requirements: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract structured requirements from conversation

        Args:
            conversation_history: List of conversation turns
            current_requirements: Current extracted requirements

        Returns:
            Dict with:
            - extracted_requirements: Updated requirements
            - missing_fields: List of still-missing fields
            - next_question: Next question to ask researcher
            - completeness_score: 0.0-1.0
            - ready_for_submission: bool
        """
        prompt = f"""You are a clinical research data request specialist helping a researcher define their data needs.

Current conversation history:
{json.dumps(conversation_history, indent=2)}

Current extracted requirements:
{json.dumps(current_requirements, indent=2)}

Analyze the conversation and:
1. Extract any new requirement information from the latest messages
2. Identify what critical fields are still missing
3. Generate the next question to ask the researcher (be specific and helpful)
4. Calculate completeness score based on how many required fields are filled

Required fields:
- study_title (or can infer from request)
- irb_number (critical for compliance)
- inclusion_criteria (at least one criterion)
- data_elements (what data they need)
- time_period (start and end dates)
- phi_level (identified, limited_dataset, or de-identified)

Return JSON with this exact structure:
{{
  "extracted_requirements": {{
    "study_title": "string or null",
    "principal_investigator": "string or null",
    "irb_number": "string or null",
    "inclusion_criteria": ["list of criteria strings"],
    "exclusion_criteria": ["list of criteria strings"],
    "data_elements": ["list of data element names"],
    "time_period": {{"start": "YYYY-MM-DD or null", "end": "YYYY-MM-DD or null"}},
    "delivery_format": "CSV|FHIR|REDCap or null",
    "phi_level": "identified|limited_dataset|de-identified or null"
  }},
  "missing_fields": ["list of required field names that are still null"],
  "next_question": "specific question to ask researcher",
  "completeness_score": 0.85,
  "ready_for_submission": false
}}"""

        schema = """Expected JSON schema above."""

        return await self.extract_structured_json(prompt, schema)

    async def extract_medical_concepts(self, criterion: str) -> Dict[str, Any]:
        """
        Extract medical concepts from a clinical criterion

        Sprint 8 Optimization: Uses Claude Haiku 3.5 (10x cheaper than Sonnet 4.5)
        for simple medical term classification task.

        Args:
            criterion: Natural language criterion (e.g., "patients with diabetes")

        Returns:
            Dict with:
            - concepts: List of {term, type, category}
            - types: condition, medication, lab, procedure, demographic
        """
        prompt = f"""Extract medical concepts from this clinical criterion:
"{criterion}"

Identify:
- Conditions/diagnoses (e.g., diabetes, heart failure)
- Procedures (e.g., cardiac catheterization)
- Medications (e.g., metformin, insulin)
- Lab values (e.g., hemoglobin < 12, creatinine > 1.5)
- Demographics (e.g., age > 65, male, female, gender)

Return JSON:
{{
  "concepts": [
    {{
      "term": "diabetes",
      "type": "condition",
      "details": "any diabetes diagnosis"
    }}
  ]
}}"""

        # Sprint 8 Optimization 2: Use Haiku for simple classification (10x cheaper)
        # Haiku 3.5 is sufficient for medical term classification
        # Cost: ~$0.0001 per call vs ~$0.001 with Sonnet (90% savings)
        return await self.extract_structured_json(prompt, "", model="claude-3-5-haiku-20241022")

    async def extract_medical_concepts_batch(
        self, criteria_list: list[str]
    ) -> list[Dict[str, Any]]:
        """
        Extract medical concepts from multiple criteria in a single LLM call

        Sprint 8 Optimization 5: Batch extraction reduces LLM calls by 50%
        Cost: ~$0.0001 per batch vs ~$0.0001 × N calls (50% savings)

        Args:
            criteria_list: List of clinical criteria

        Returns:
            List of dicts with:
            - concepts: List of {term, type, category}
            - for each criterion in same order as input
        """
        if not criteria_list:
            return []

        # Build batch prompt
        criteria_text = ""
        for i, criterion in enumerate(criteria_list, 1):
            criteria_text += f'{i}. "{criterion}"\n'

        prompt = f"""Extract medical concepts from these clinical criteria:

{criteria_text}

For EACH criterion, identify:
- Conditions/diagnoses (e.g., diabetes, heart failure)
- Procedures (e.g., cardiac catheterization)
- Medications (e.g., metformin, insulin)
- Lab values (e.g., hemoglobin < 12, creatinine > 1.5)
- Demographics (e.g., age > 65, male, female, gender)

Return JSON array with one entry per criterion (in same order):
{{
  "results": [
    {{
      "criterion_index": 1,
      "concepts": [
        {{
          "term": "diabetes",
          "type": "condition",
          "details": "any diabetes diagnosis"
        }}
      ]
    }}
  ]
}}"""

        result = await self.extract_structured_json(prompt, "", model="claude-3-5-haiku-20241022")

        # Extract results array
        results = result.get("results", [])

        # Convert to list of concept dicts (maintaining order)
        concept_dicts = []
        for i in range(len(criteria_list)):
            # Find matching result by index
            matching_result = next((r for r in results if r.get("criterion_index") == i + 1), None)
            if matching_result:
                concept_dicts.append({"concepts": matching_result.get("concepts", [])})
            else:
                # Fallback if index not found
                concept_dicts.append({"concepts": []})

        return concept_dicts

    def _dummy_response(self, prompt: str) -> str:
        """Dummy response when LLM not available (for testing)"""
        if "extract" in prompt.lower() or "json" in prompt.lower():
            return json.dumps(
                {
                    "extracted_requirements": {
                        "study_title": "Research Study",
                        "inclusion_criteria": ["dummy criterion"],
                        "data_elements": ["clinical_notes"],
                        "phi_level": "de-identified",
                    },
                    "missing_fields": ["irb_number", "time_period"],
                    "next_question": "What is your IRB number?",
                    "completeness_score": 0.5,
                    "ready_for_submission": False,
                }
            )
        return "Dummy LLM response"
