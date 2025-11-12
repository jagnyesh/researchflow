"""
Agent Adapter for LangGraph Migration (Phase 2.1)

Bridges custom BaseAgent-based agents with LangGraph's state-based workflow.
Enables reusing existing agents (PhenotypeAgent, ExtractionAgent, QAAgent, etc.)
without rewriting them for LangGraph.

Key responsibilities:
1. Translate LangGraph state → BaseAgent context
2. Call existing BaseAgent.handle_task() method
3. Translate BaseAgent result → LangGraph state updates

This is a critical migration component that maintains backward compatibility
while enabling LangGraph orchestration.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class LangGraphAgentAdapter:
    """
    Adapter that bridges BaseAgent agents with LangGraph state-based workflow.

    Allows reusing existing agents (app/agents/*.py) without modification.
    Translates between two patterns:
    - BaseAgent pattern: agent.handle_task(task, context) → result dict
    - LangGraph pattern: node(state) → state updates

    Example:
        ```python
        # Wrap existing agent
        phenotype_agent = PhenotypeValidationAgent(database_url=db_url)
        adapter = LangGraphAgentAdapter(phenotype_agent)

        # Use in LangGraph node
        async def phenotype_node(state: FullWorkflowState):
            result = await adapter.execute_with_state(
                task="validate_feasibility",
                state=state
            )
            return result  # State updates
        ```
    """

    def __init__(self, base_agent):
        """
        Initialize adapter with a BaseAgent instance.

        Args:
            base_agent: Instance of BaseAgent subclass (PhenotypeAgent, etc.)
        """
        self.agent = base_agent
        self.agent_name = base_agent.__class__.__name__
        logger.info(f"[LangGraphAgentAdapter] Initialized for {self.agent_name}")

    async def execute_with_state(self, task: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute agent task and return LangGraph state updates.

        This is the main adapter method. It:
        1. Extracts context from LangGraph state
        2. Calls BaseAgent.handle_task()
        3. Maps agent result to state updates

        Args:
            task: Agent task name (e.g., "validate_feasibility")
            state: LangGraph FullWorkflowState dict

        Returns:
            State updates dict to merge into workflow state

        Example:
            ```python
            # State before
            state = {
                "request_id": "REQ-123",
                "requirements": {...},
                "feasible": False
            }

            # Execute agent
            updates = await adapter.execute_with_state(
                "validate_feasibility",
                state
            )

            # Updates returned
            updates = {
                "feasible": True,
                "feasibility_score": 0.85,
                "estimated_cohort_size": 1500,
                "phenotype_sql": "SELECT ..."
            }
            ```
        """
        logger.info(
            f"[LangGraphAgentAdapter] {self.agent_name}.execute_with_state(task={task}, "
            f"request_id={state.get('request_id')})"
        )

        # Build agent context from state
        context = self._state_to_context(state)

        # Call existing BaseAgent.handle_task() method
        try:
            result = await self.agent.handle_task(task, context)
            logger.info(f"[LangGraphAgentAdapter] {self.agent_name} completed successfully")
        except Exception as e:
            logger.error(f"[LangGraphAgentAdapter] {self.agent_name} failed: {e}")
            # Return error state updates
            return {"error": str(e), "updated_at": datetime.now().isoformat()}

        # Map agent result to state updates
        state_updates = self._result_to_state(result, task)

        logger.info(
            f"[LangGraphAgentAdapter] {self.agent_name} returned {len(state_updates)} state updates"
        )

        return state_updates

    def _state_to_context(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert LangGraph state to BaseAgent context.

        BaseAgent.handle_task() expects a context dict with specific fields.
        This method extracts relevant fields from FullWorkflowState.

        Args:
            state: LangGraph FullWorkflowState

        Returns:
            Context dict for BaseAgent.handle_task()
        """
        # Build context from state fields
        # Include all fields that agents might need
        context = {
            # Request metadata
            "request_id": state.get("request_id"),
            "current_state": state.get("current_state"),
            # Requirements (for phenotype/extraction agents)
            "requirements": state.get("requirements", {}),
            "requirements_complete": state.get("requirements_complete", False),
            # Feasibility (for extraction/qa agents)
            "phenotype_sql": state.get("phenotype_sql"),
            "parameters": state.get(
                "sql_parameters", {}
            ),  # SQL parameters for parameterized queries
            "feasible": state.get("feasible", False),
            "estimated_cohort_size": state.get("estimated_cohort_size"),
            # Meeting info (for extraction agent)
            "meeting_scheduled": state.get("meeting_scheduled", False),
            "meeting_details": state.get("meeting_details"),
            # Extraction data (for QA agent)
            "extraction_complete": state.get("extraction_complete", False),
            "extracted_data_summary": state.get("extracted_data_summary"),
            # Researcher info (for delivery agent)
            "researcher_info": state.get("researcher_info", {}),
            "researcher_request": state.get("researcher_request"),
            # Generic fields agents may use
            "created_at": state.get("created_at"),
            "updated_at": state.get("updated_at"),
        }

        return context

    def _result_to_state(self, result: Dict[str, Any], task: str) -> Dict[str, Any]:
        """
        Convert BaseAgent result to LangGraph state updates.

        Maps agent result fields to FullWorkflowState fields.
        Different agents return different result structures.

        Args:
            result: Result dict from BaseAgent.handle_task()
            task: Task name (for logging/debugging)

        Returns:
            State updates dict

        Agent Result Patterns:
        - PhenotypeAgent: {feasible, feasibility_score, cohort_size, sql}
        - ExtractionAgent: {extraction_complete, data_summary}
        - QAAgent: {overall_status, qa_report, passed}
        - DeliveryAgent: {delivered, delivery_info}
        """
        state_updates = {"updated_at": datetime.now().isoformat()}

        # Map common fields
        if "error" in result:
            state_updates["error"] = result["error"]

        # Agent-specific mapping
        # Phenotype Agent results
        if "feasible" in result:
            state_updates["feasible"] = result["feasible"]
        if "feasibility_score" in result:
            state_updates["feasibility_score"] = result["feasibility_score"]
        if "estimated_cohort_size" in result or "cohort_size" in result:
            state_updates["estimated_cohort_size"] = result.get(
                "estimated_cohort_size", result.get("cohort_size")
            )
        if "phenotype_sql" in result or "sql" in result:
            state_updates["phenotype_sql"] = result.get("phenotype_sql", result.get("sql"))

        # Extraction Agent results
        if "extraction_complete" in result:
            state_updates["extraction_complete"] = result["extraction_complete"]
        if "extracted_data_summary" in result or "data_summary" in result:
            state_updates["extracted_data_summary"] = result.get(
                "extracted_data_summary", result.get("data_summary")
            )

        # QA Agent results
        if "overall_status" in result:
            state_updates["overall_status"] = result["overall_status"]
        if "qa_report" in result:
            state_updates["qa_report"] = result["qa_report"]
        if "passed" in result:
            # QA agent returns 'passed' boolean, map to overall_status
            state_updates["overall_status"] = "passed" if result["passed"] else "failed"

        # Delivery Agent results
        if "delivered" in result:
            state_updates["delivered"] = result["delivered"]
        if "delivery_info" in result:
            state_updates["delivery_info"] = result["delivery_info"]
        if "delivery_location" in result:
            state_updates["delivery_location"] = result["delivery_location"]

        # Approval-related results (from any agent)
        if "needs_approval" in result:
            # Agents can request human approval
            state_updates["escalation_reason"] = result.get(
                "escalation_reason", "Agent requested human review"
            )

        logger.debug(
            f"[LangGraphAgentAdapter] Mapped {task} result to state updates: {list(state_updates.keys())}"
        )

        return state_updates

    async def execute_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Direct passthrough to BaseAgent.handle_task().

        Use this when you already have context and don't need state mapping.
        This is a convenience method for backward compatibility.

        Args:
            task: Agent task name
            context: Agent context dict

        Returns:
            Agent result dict (not state updates)
        """
        return await self.agent.handle_task(task, context)

    def get_agent_info(self) -> Dict[str, Any]:
        """
        Get metadata about the wrapped agent.

        Returns:
            Dict with agent name, type, capabilities
        """
        return {
            "agent_name": self.agent_name,
            "agent_type": type(self.agent).__name__,
            "agent_module": type(self.agent).__module__,
            "has_handle_task": hasattr(self.agent, "handle_task"),
            "has_execute_task": hasattr(self.agent, "execute_task"),
        }


# ============================================================================
# Helper Functions
# ============================================================================


def create_adapter_for_agent(agent_instance) -> LangGraphAgentAdapter:
    """
    Factory function to create adapter for any BaseAgent.

    Args:
        agent_instance: Instance of any BaseAgent subclass

    Returns:
        LangGraphAgentAdapter configured for the agent

    Example:
        ```python
        from app.agents.phenotype_agent import PhenotypeValidationAgent

        agent = PhenotypeValidationAgent(database_url=db_url)
        adapter = create_adapter_for_agent(agent)

        # Use in LangGraph node
        result = await adapter.execute_with_state("validate", state)
        ```
    """
    return LangGraphAgentAdapter(agent_instance)


def create_adapters_for_all_agents(
    phenotype_agent=None,
    extraction_agent=None,
    qa_agent=None,
    delivery_agent=None,
    requirements_agent=None,
    calendar_agent=None,
) -> Dict[str, LangGraphAgentAdapter]:
    """
    Create adapters for all provided agents.

    Convenience function for initializing multiple adapters at once.

    Args:
        phenotype_agent: PhenotypeValidationAgent instance
        extraction_agent: DataExtractionAgent instance
        qa_agent: QualityAssuranceAgent instance
        delivery_agent: DataDeliveryAgent instance
        requirements_agent: RequirementsAgent instance
        calendar_agent: CalendarAgent instance

    Returns:
        Dict mapping agent names to adapters

    Example:
        ```python
        adapters = create_adapters_for_all_agents(
            phenotype_agent=PhenotypeValidationAgent(db_url),
            extraction_agent=DataExtractionAgent(db_url),
            qa_agent=QualityAssuranceAgent()
        )

        # Use adapters in nodes
        result = await adapters["phenotype"].execute_with_state("validate", state)
        ```
    """
    adapters = {}

    if phenotype_agent:
        adapters["phenotype"] = LangGraphAgentAdapter(phenotype_agent)
    if extraction_agent:
        adapters["extraction"] = LangGraphAgentAdapter(extraction_agent)
    if qa_agent:
        adapters["qa"] = LangGraphAgentAdapter(qa_agent)
    if delivery_agent:
        adapters["delivery"] = LangGraphAgentAdapter(delivery_agent)
    if requirements_agent:
        adapters["requirements"] = LangGraphAgentAdapter(requirements_agent)
    if calendar_agent:
        adapters["calendar"] = LangGraphAgentAdapter(calendar_agent)

    logger.info(f"[create_adapters_for_all_agents] Created {len(adapters)} adapters")

    return adapters


# ============================================================================
# Sprint 6.5 Migration Notes
# ============================================================================

# MIGRATION BENEFIT:
# - Reuses all existing agent code without modification
# - BaseAgent.handle_task() continues working as-is
# - Agents don't need to know about LangGraph state structure
# - Clear separation between orchestration (LangGraph) and business logic (agents)
#
# USAGE IN LANGGRAPH NODES:
# Instead of:
#   async def phenotype_node(state):
#       result = await phenotype_agent.handle_task("validate", {...})
#       return {"feasible": result["feasible"], ...}  # Manual mapping
#
# Use adapter:
#   async def phenotype_node(state):
#       return await phenotype_adapter.execute_with_state("validate", state)
#
# FUTURE ENHANCEMENTS:
# - Add caching for repeated context builds
# - Add telemetry/metrics collection
# - Add retry logic (currently in BaseAgent, could move here)
# - Add result validation against state schema
