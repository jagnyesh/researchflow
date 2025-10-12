"""
Requirements Gathering Agent

Converses with researchers to extract structured data requirements using LLM.
Validates completeness and routes to phenotype validation when ready.
"""

from typing import Dict, Any
import logging
from datetime import datetime
from .base_agent import BaseAgent
from ..utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


class RequirementsAgent(BaseAgent):
    """
    Agent for gathering research data requirements through conversation

    Responsibilities:
    - Conduct multi-turn conversation with researcher
    - Extract structured requirements (criteria, data elements, IRB info)
    - Map medical concepts to standard terminologies
    - Validate completeness
    - Route to phenotype agent when ready
    """

    def __init__(self, orchestrator=None):
        super().__init__(agent_id="requirements_agent", orchestrator=orchestrator)
        self.llm_client = LLMClient()
        self.conversation_state = {}  # Store conversation state per request

    async def execute_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute requirements gathering task"""
        if task == "gather_requirements":
            return await self._gather_requirements(context)
        elif task == "continue_conversation":
            return await self._continue_conversation(context)
        else:
            raise ValueError(f"Unknown task: {task}")

    async def _gather_requirements(self, context: Dict) -> Dict[str, Any]:
        """
        Start or continue requirements gathering conversation

        Args:
            context: Contains initial_request, request_id, researcher_info,
                    conversation_history (optional), user_response (optional)

        Returns:
            Dict with:
            - requirements_complete: bool
            - structured_requirements: Dict (if complete)
            - next_question: str (if not complete)
            - conversation_state: current state
        """
        request_id = context.get('request_id')
        initial_request = context.get('initial_request')
        conversation_history = context.get('conversation_history', [])
        user_response = context.get('user_response')

        # Initialize conversation state if new
        if request_id not in self.conversation_state:
            self.conversation_state[request_id] = {
                "requirements": {
                    "study_title": None,
                    "principal_investigator": None,
                    "irb_number": None,
                    "inclusion_criteria": [],
                    "exclusion_criteria": [],
                    "data_elements": [],
                    "time_period": {"start": None, "end": None},
                    "estimated_cohort_size": None,
                    "delivery_format": None,
                    "phi_level": None
                },
                "questions_asked": [],
                "completeness_score": 0.0
            }

            # Add initial request to conversation
            conversation_history = [
                {"role": "user", "content": initial_request, "timestamp": datetime.now().isoformat()}
            ]

        # Add user response if provided
        if user_response:
            conversation_history.append({
                "role": "user",
                "content": user_response,
                "timestamp": datetime.now().isoformat()
            })

        state = self.conversation_state[request_id]

        logger.info(f"[{self.agent_id}] Extracting requirements from conversation (turns: {len(conversation_history)})")

        # Use LLM to extract structured info from conversation
        try:
            analysis = await self.llm_client.extract_requirements(
                conversation_history=conversation_history,
                current_requirements=state['requirements']
            )

            # Update state
            state['requirements'] = analysis['extracted_requirements']
            state['completeness_score'] = analysis['completeness_score']

            # Add assistant question to conversation
            if not analysis['ready_for_submission']:
                conversation_history.append({
                    "role": "assistant",
                    "content": analysis['next_question'],
                    "timestamp": datetime.now().isoformat()
                })
                state['questions_asked'].append(analysis['next_question'])

            logger.info(
                f"[{self.agent_id}] Completeness: {analysis['completeness_score']:.1%}, "
                f"Ready: {analysis['ready_for_submission']}"
            )

            # Check if requirements are complete
            if analysis['ready_for_submission']:
                # Validate and structure requirements
                final_requirements = await self._validate_and_structure_requirements(
                    state['requirements']
                )

                # Save to database (TODO: implement when DB is connected)
                await self._save_requirements(request_id, final_requirements)

                logger.info(f"[{self.agent_id}] Requirements complete for {request_id}")

                # IMPORTANT: Requirements must be reviewed by informatician for medical accuracy (Gap #3)
                # Transition to REQUIREMENTS_REVIEW state for human approval
                logger.info(
                    f"[{self.agent_id}] Requirements extracted, requesting informatician review"
                )

                return {
                    "requirements_complete": True,
                    "structured_requirements": final_requirements,
                    "conversation_history": conversation_history,
                    "completeness_score": analysis['completeness_score'],
                    "requires_approval": True,  # Flag for orchestrator
                    "approval_type": "requirements",  # Type of approval needed
                    "next_agent": None,  # Wait for approval - orchestrator will route
                    "next_task": None,
                    "additional_context": {
                        "requirements": final_requirements,
                        "approval_data": {
                            "structured_requirements": final_requirements,
                            "completeness_score": analysis['completeness_score'],
                            "conversation_history": conversation_history[-5:] if len(conversation_history) > 5 else conversation_history,  # Last 5 turns
                            "inclusion_criteria": final_requirements.get('inclusion_criteria', []),
                            "exclusion_criteria": final_requirements.get('exclusion_criteria', []),
                            "data_elements": final_requirements.get('data_elements', [])
                        }
                    }
                }
            else:
                # Continue conversation
                return {
                    "requirements_complete": False,
                    "next_question": analysis['next_question'],
                    "completeness_score": analysis['completeness_score'],
                    "current_requirements": state['requirements'],
                    "missing_fields": analysis['missing_fields'],
                    "conversation_history": conversation_history
                }

        except Exception as e:
            logger.error(f"[{self.agent_id}] Failed to extract requirements: {str(e)}")
            raise

    async def _continue_conversation(self, context: Dict) -> Dict[str, Any]:
        """Handle continuation of conversation with user response"""
        return await self._gather_requirements(context)

    async def _validate_and_structure_requirements(self, requirements: Dict) -> Dict:
        """
        Validate requirements and convert to standard format

        Converts natural language criteria to structured format with medical codes
        """
        structured_requirements = requirements.copy()

        # Convert inclusion/exclusion criteria to structured format with codes
        if requirements.get('inclusion_criteria'):
            structured_requirements['inclusion_criteria'] = await self._criteria_to_structured(
                requirements['inclusion_criteria']
            )

        if requirements.get('exclusion_criteria'):
            structured_requirements['exclusion_criteria'] = await self._criteria_to_structured(
                requirements['exclusion_criteria']
            )

        # Validate dates
        if requirements.get('time_period'):
            structured_requirements['time_period'] = self._validate_dates(
                requirements['time_period']
            )

        # Set defaults
        if not structured_requirements.get('delivery_format'):
            structured_requirements['delivery_format'] = 'CSV'

        if not structured_requirements.get('phi_level'):
            structured_requirements['phi_level'] = 'de-identified'

        return structured_requirements

    async def _criteria_to_structured(self, criteria_list: list) -> list:
        """
        Convert natural language criteria to structured format

        For each criterion:
        1. Extract medical concepts using LLM
        2. Look up codes (will use terminology MCP server in future)
        3. Return structured criterion
        """
        structured_criteria = []

        for criterion in criteria_list:
            try:
                # Extract medical concepts
                concepts_data = await self.llm_client.extract_medical_concepts(criterion)

                criterion_structured = {
                    "description": criterion,
                    "concepts": concepts_data.get('concepts', []),
                    "codes": []  # Will be populated by terminology server
                }

                structured_criteria.append(criterion_structured)

            except Exception as e:
                logger.warning(f"Could not structure criterion '{criterion}': {str(e)}")
                # Fallback to simple structure
                structured_criteria.append({
                    "description": criterion,
                    "concepts": [],
                    "codes": []
                })

        return structured_criteria

    def _validate_dates(self, time_period: dict) -> dict:
        """Validate and normalize date strings"""
        # TODO: Implement date validation and normalization
        # For now, pass through
        return time_period

    async def _save_requirements(self, request_id: str, requirements: Dict):
        """Save requirements to database"""
        # TODO: Implement database save using RequirementsData model
        logger.info(f"[{self.agent_id}] Saving requirements for {request_id}")
        # For now, just log
        logger.debug(f"Requirements: {requirements}")
