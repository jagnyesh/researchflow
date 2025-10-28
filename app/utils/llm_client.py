"""
LLM Client for ResearchFlow

Wrapper for Anthropic Claude API with structured output parsing.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
import anthropic
from dotenv import load_dotenv

# Load .env file from project root when this module is imported
# This ensures ANTHROPIC_API_KEY is available before LLMClient is initialized
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_dotenv_path = os.path.join(_project_root, '.env')
load_dotenv(_dotenv_path)

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Client for interacting with Claude API

    Provides methods for structured requirement extraction, SQL generation,
    and medical terminology mapping.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not set - LLM features will be limited")
            self.client = None
        else:
            self.client = anthropic.Anthropic(api_key=self.api_key)

    async def complete(
        self,
        prompt: str,
        model: str = "claude-3-7-sonnet-20250219",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        system: Optional[str] = None
    ) -> str:
        """
        Get completion from Claude API

        Args:
            prompt: User prompt
            model: Model identifier
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
            message = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system if system else "You are a helpful clinical research data specialist.",
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = message.content[0].text
            logger.debug(f"LLM response ({len(response_text)} chars)")
            return response_text

        except Exception as e:
            logger.error(f"LLM API error: {str(e)}")
            raise

    async def extract_structured_json(
        self,
        prompt: str,
        schema_description: str,
        model: str = "claude-3-7-sonnet-20250219",
        system: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract structured JSON from text using LLM

        Args:
            prompt: Input text to parse
            schema_description: Description of expected JSON schema
            model: Model to use
            system: Optional system prompt

        Returns:
            Parsed JSON object
        """
        full_prompt = f"""{prompt}

{schema_description}

Return ONLY valid JSON, no other text."""

        response = await self.complete(full_prompt, model=model, temperature=0.3, system=system)

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
        self,
        conversation_history: list,
        current_requirements: Dict[str, Any]
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
- Demographics (e.g., age > 65, female)

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

        return await self.extract_structured_json(prompt, "")

    def _dummy_response(self, prompt: str) -> str:
        """Dummy response when LLM not available (for testing)"""
        if "extract" in prompt.lower() or "json" in prompt.lower():
            return json.dumps({
                "extracted_requirements": {
                    "study_title": "Research Study",
                    "inclusion_criteria": ["dummy criterion"],
                    "data_elements": ["clinical_notes"],
                    "phi_level": "de-identified"
                },
                "missing_fields": ["irb_number", "time_period"],
                "next_question": "What is your IRB number?",
                "completeness_score": 0.5,
                "ready_for_submission": False
            })
        return "Dummy LLM response"
