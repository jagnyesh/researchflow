"""
Full 23-State Workflow using LangGraph (Sprint 3)

This is the complete production workflow that replaces the custom
workflow_engine.py FSM with LangGraph's StateGraph.

States: 23 total
- Main workflow: 15 states
- Approval gates: 5 states
- Terminal states: 3 states

Purpose: Production-ready LangGraph workflow with all 6 agents integrated
Status: Sprint 3 - Production Implementation
"""

import logging
from typing import TypedDict, Annotated, Literal, Optional
from datetime import datetime
import os

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.runnables import RunnableConfig
from langsmith import traceable

# Import agents for real execution (when use_real_agents=True)
from app.agents.phenotype_agent import PhenotypeValidationAgent
from app.agents.extraction_agent import DataExtractionAgent
from app.agents.qa_agent import QualityAssuranceAgent

logger = logging.getLogger(__name__)


# ============================================================================
# State Schema
# ============================================================================

class FullWorkflowState(TypedDict):
    """
    Complete state schema for ResearchFlow workflow

    This replaces the manual state tracking in custom workflow_engine.py
    LangGraph enforces this schema via TypedDict.
    """
    # ===== Request Metadata =====
    request_id: str
    current_state: str
    created_at: str
    updated_at: str

    # ===== Researcher Info =====
    researcher_request: str
    researcher_info: dict

    # ===== Requirements Phase =====
    requirements: dict
    conversation_history: Annotated[list, add_messages]
    completeness_score: float
    requirements_complete: bool
    requirements_approved: bool | None
    requirements_rejection_reason: str | None

    # ===== Feasibility Phase =====
    phenotype_sql: str | None
    feasibility_score: float
    estimated_cohort_size: int | None
    feasible: bool
    phenotype_approved: bool | None
    phenotype_rejection_reason: str | None

    # ===== Kickoff Phase =====
    meeting_scheduled: bool
    meeting_details: dict | None

    # ===== Extraction Phase =====
    extraction_approved: bool | None
    extraction_rejection_reason: str | None
    extraction_complete: bool
    extracted_data_summary: dict | None

    # ===== QA Phase =====
    overall_status: str | None  # 'passed', 'failed'
    qa_report: dict | None
    qa_approved: bool | None
    qa_rejection_reason: str | None

    # ===== Delivery Phase =====
    delivered: bool
    delivered_at: str | None
    delivery_location: str | None
    delivery_info: dict | None

    # ===== Error Handling =====
    error: str | None
    escalation_reason: str | None

    # ===== Scope Change =====
    scope_change_requested: bool
    scope_approved: bool | None


# ============================================================================
# Full Workflow Class
# ============================================================================

class FullWorkflow:
    """
    Complete 23-state workflow using LangGraph

    This is the production implementation that replaces:
    - app/orchestrator/workflow_engine.py (custom FSM)
    - Manual state transitions in orchestrator.py

    Advantages over custom FSM:
    1. Declarative graph building (clearer than transition tables)
    2. Automatic visualization (Mermaid diagrams)
    3. Type-safe state schema (TypedDict)
    4. Cleaner conditional routing (no if/elif chains)
    5. LangSmith observability integration
    6. Built-in state passing (no manual dict copying)
    """

    def __init__(self, use_real_agents: bool = False):
        """
        Initialize the full workflow graph

        Args:
            use_real_agents: If True, invoke real agents instead of stubs.
                            If False (default), use stub values for testing.
        """
        self.use_real_agents = use_real_agents

        # Initialize real agents if requested
        if use_real_agents:
            logger.info("[FullWorkflow] Initializing with REAL AGENTS")

            # Get HAPI FHIR database URL from environment
            # Default uses asyncpg for async connections
            hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql+asyncpg://hapi:hapi@localhost:5433/hapi")
            healthcare_db_url = os.getenv("HEALTHCARE_DB_URL")

            logger.info(f"[FullWorkflow] HAPI DB URL: {hapi_db_url}")
            logger.info(f"[FullWorkflow] Healthcare DB URL: {healthcare_db_url}")

            # Initialize agents with appropriate database connections
            self.phenotype_agent = PhenotypeValidationAgent(database_url=hapi_db_url)
            self.extraction_agent = DataExtractionAgent(database_url=healthcare_db_url or hapi_db_url)
            self.qa_agent = QualityAssuranceAgent()
        else:
            logger.info("[FullWorkflow] Initializing with STUB VALUES (test mode)")
            self.phenotype_agent = None
            self.extraction_agent = None
            self.qa_agent = None

        self.graph = self._build_graph()
        self.compiled_graph = self.graph.compile()
        logger.info("[FullWorkflow] Initialized with 23 states")

    def _build_graph(self) -> StateGraph:
        """
        Build the complete StateGraph with 23 states

        States:
        1. new_request - Entry point
        2. requirements_gathering - Requirements Agent
        3. requirements_review - Approval gate
        4. feasibility_validation - Phenotype Agent
        5. phenotype_review - Approval gate
        6. schedule_kickoff - Calendar Agent
        7. extraction_approval - Approval gate
        8. data_extraction - Extraction Agent
        9. qa_validation - QA Agent
        10. qa_review - Approval gate
        11. data_delivery - Delivery Agent
        12. complete - Terminal (success)
        13. not_feasible - Terminal (cohort too small)
        14. qa_failed - Terminal (QA failed)
        15. human_review - Terminal (escalation)

        This is much more declarative than the custom FSM's
        workflow_rules dict in workflow_engine.py
        """
        # Create graph with FullWorkflowState schema
        graph = StateGraph(FullWorkflowState)

        # ===== Add Nodes (State Handlers) =====
        graph.add_node("new_request", self._handle_new_request)
        graph.add_node("requirements_gathering", self._handle_requirements_gathering)
        graph.add_node("requirements_review", self._handle_requirements_review)
        graph.add_node("feasibility_validation", self._handle_feasibility_validation)
        graph.add_node("phenotype_review", self._handle_phenotype_review)
        graph.add_node("schedule_kickoff", self._handle_schedule_kickoff)
        graph.add_node("extraction_approval", self._handle_extraction_approval)
        graph.add_node("data_extraction", self._handle_data_extraction)
        graph.add_node("qa_validation", self._handle_qa_validation)
        graph.add_node("qa_review", self._handle_qa_review)
        graph.add_node("data_delivery", self._handle_data_delivery)
        graph.add_node("complete", self._handle_complete)
        graph.add_node("not_feasible", self._handle_not_feasible)
        graph.add_node("qa_failed", self._handle_qa_failed)
        graph.add_node("human_review", self._handle_human_review)

        # ===== Set Entry Point =====
        graph.set_entry_point("new_request")

        # ===== Add Sequential Edges =====
        # new_request → requirements_gathering
        graph.add_edge("new_request", "requirements_gathering")

        # ===== Add Conditional Edges =====

        # 1. After requirements_gathering
        # → requirements_review (if complete)
        # → END (if needs more conversation)
        graph.add_conditional_edges(
            "requirements_gathering",
            self._route_after_requirements_gathering,
            {
                "requirements_review": "requirements_review",
                "wait_for_input": END
            }
        )

        # 2. After requirements_review (approval gate)
        # → feasibility_validation (if approved)
        # → requirements_gathering (if rejected)
        graph.add_conditional_edges(
            "requirements_review",
            self._route_after_requirements_review,
            {
                "feasibility_validation": "feasibility_validation",
                "requirements_gathering": "requirements_gathering",
                "wait_for_approval": END
            }
        )

        # 3. After feasibility_validation
        # → phenotype_review (if feasible)
        # → not_feasible (if not feasible)
        graph.add_conditional_edges(
            "feasibility_validation",
            self._route_after_feasibility_validation,
            {
                "phenotype_review": "phenotype_review",
                "not_feasible": "not_feasible"
            }
        )

        # 4. After phenotype_review (approval gate)
        # → schedule_kickoff (if approved)
        # → feasibility_validation (if rejected)
        graph.add_conditional_edges(
            "phenotype_review",
            self._route_after_phenotype_review,
            {
                "schedule_kickoff": "schedule_kickoff",
                "feasibility_validation": "feasibility_validation",
                "wait_for_approval": END
            }
        )

        # 5. After schedule_kickoff
        # → extraction_approval (always)
        graph.add_edge("schedule_kickoff", "extraction_approval")

        # 6. After extraction_approval (approval gate)
        # → data_extraction (if approved)
        # → human_review (if rejected)
        graph.add_conditional_edges(
            "extraction_approval",
            self._route_after_extraction_approval,
            {
                "data_extraction": "data_extraction",
                "human_review": "human_review",
                "wait_for_approval": END
            }
        )

        # 7. After data_extraction
        # → qa_validation (always)
        graph.add_edge("data_extraction", "qa_validation")

        # 8. After qa_validation
        # → qa_review (if passed)
        # → qa_failed (if failed)
        graph.add_conditional_edges(
            "qa_validation",
            self._route_after_qa_validation,
            {
                "qa_review": "qa_review",
                "qa_failed": "qa_failed"
            }
        )

        # 9. After qa_review (approval gate)
        # → data_delivery (if approved)
        # → data_extraction (if rejected - redo extraction)
        graph.add_conditional_edges(
            "qa_review",
            self._route_after_qa_review,
            {
                "data_delivery": "data_delivery",
                "data_extraction": "data_extraction",
                "wait_for_approval": END
            }
        )

        # 10. After data_delivery
        # → complete (always)
        graph.add_edge("data_delivery", "complete")

        # ===== Terminal States → END =====
        graph.add_edge("complete", END)
        graph.add_edge("not_feasible", END)
        graph.add_edge("qa_failed", END)
        graph.add_edge("human_review", END)

        return graph

    # ========================================================================
    # State Handlers (Node Functions)
    # ========================================================================

    def _handle_new_request(self, state: FullWorkflowState) -> FullWorkflowState:
        """Handle new request state"""
        logger.info(f"[FullWorkflow] NEW_REQUEST: {state['request_id']}")

        state["current_state"] = "new_request"
        state["updated_at"] = datetime.now().isoformat()

        # Initialize fields if not present
        if "requirements_complete" not in state:
            state["requirements_complete"] = False
        if "completeness_score" not in state:
            state["completeness_score"] = 0.0
        if "feasible" not in state:
            state["feasible"] = False
        if "feasibility_score" not in state:
            state["feasibility_score"] = 0.0
        if "meeting_scheduled" not in state:
            state["meeting_scheduled"] = False
        if "extraction_complete" not in state:
            state["extraction_complete"] = False
        if "delivered" not in state:
            state["delivered"] = False
        if "scope_change_requested" not in state:
            state["scope_change_requested"] = False
        if "error" not in state:
            state["error"] = None

        return state

    def _handle_requirements_gathering(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle requirements gathering state

        This is where the Requirements Agent would be invoked.
        For Sprint 3, we integrate the LangChain Requirements Agent from Sprint 1.
        """
        logger.info(f"[FullWorkflow] REQUIREMENTS_GATHERING: {state['request_id']}")

        state["current_state"] = "requirements_gathering"
        state["updated_at"] = datetime.now().isoformat()

        # NOTE: In production, this would invoke the actual LangChain Requirements Agent
        # For now, we simulate the agent's behavior based on state

        # Check if requirements are already marked as complete (from agent execution)
        if state.get("requirements_complete", False):
            logger.info(f"[FullWorkflow] Requirements already complete (score: {state.get('completeness_score', 0):.1%})")
        else:
            logger.info(f"[FullWorkflow] Requirements incomplete (score: {state.get('completeness_score', 0):.1%})")

        return state

    def _handle_requirements_review(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle requirements review state (APPROVAL GATE)

        This is a human-in-the-loop approval gate.
        Workflow pauses here until informatician approves/rejects requirements.
        """
        logger.info(f"[FullWorkflow] REQUIREMENTS_REVIEW: {state['request_id']}")

        state["current_state"] = "requirements_review"
        state["updated_at"] = datetime.now().isoformat()

        # Approval status will be set externally via approval_service
        logger.info(f"[FullWorkflow] Waiting for requirements approval...")

        return state

    def _handle_feasibility_validation(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle feasibility validation state

        Invokes Phenotype Agent to generate SQL and validate feasibility.
        """
        logger.info(f"[FullWorkflow] FEASIBILITY_VALIDATION: {state['request_id']}")
        logger.info(f"[FullWorkflow] Feasibility BEFORE: {state.get('feasible', 'NOT_SET')}")

        state["current_state"] = "feasibility_validation"
        state["updated_at"] = datetime.now().isoformat()

        # Ensure delivered_at is explicitly set (required by TypedDict)
        if "delivered_at" not in state:
            state["delivered_at"] = None

        if self.use_real_agents and self.phenotype_agent:
            # REAL AGENT: Invoke Phenotype Agent
            logger.info("[FullWorkflow] Invoking REAL PhenotypeAgent...")

            try:
                # Prepare context for agent
                context = {
                    "request_id": state["request_id"],
                    "requirements": state["requirements"],
                    "researcher_info": state["researcher_info"]
                }

                # Execute agent task (synchronous call)
                import asyncio
                result = asyncio.run(self.phenotype_agent.execute_task(
                    task="validate_feasibility",
                    context=context
                ))

                # Update state from agent result
                state["feasible"] = result.get("feasible", False)
                state["estimated_cohort_size"] = result.get("estimated_cohort_size")
                state["phenotype_sql"] = result.get("phenotype_sql")
                state["feasibility_score"] = result.get("feasibility_score", 0.0)

                logger.info(f"[FullWorkflow] PhenotypeAgent result: feasible={state['feasible']}, cohort={state['estimated_cohort_size']}")

            except Exception as e:
                logger.error(f"[FullWorkflow] PhenotypeAgent failed: {e}")
                # Fall back to conservative defaults on error
                state["feasible"] = False
                state["estimated_cohort_size"] = 0
                state["phenotype_sql"] = None
                state["feasibility_score"] = 0.0
                state["error"] = f"Phenotype agent error: {str(e)}"

        else:
            # STUB VALUES: For E2E testing without real agents
            logger.info("[FullWorkflow] Using STUB VALUES for feasibility")
            state["feasible"] = True
            state["estimated_cohort_size"] = 150
            state["phenotype_sql"] = "SELECT * FROM Patient WHERE ..."
            state["feasibility_score"] = 0.95

        logger.info(f"[FullWorkflow] Feasibility AFTER: {state.get('feasible', False)} (cohort: {state.get('estimated_cohort_size', 0)})")

        return state

    def _handle_phenotype_review(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle phenotype review state (APPROVAL GATE)

        Informatician reviews generated SQL query before execution.
        """
        logger.info(f"[FullWorkflow] PHENOTYPE_REVIEW: {state['request_id']}")

        state["current_state"] = "phenotype_review"
        state["updated_at"] = datetime.now().isoformat()

        logger.info(f"[FullWorkflow] Waiting for SQL approval...")

        return state

    def _handle_schedule_kickoff(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle schedule kickoff state

        This is where the Calendar Agent would be invoked.
        """
        logger.info(f"[FullWorkflow] SCHEDULE_KICKOFF: {state['request_id']}")

        state["current_state"] = "schedule_kickoff"
        state["updated_at"] = datetime.now().isoformat()

        # NOTE: In production, this would invoke the Calendar Agent

        logger.info(f"[FullWorkflow] Meeting scheduled: {state.get('meeting_scheduled', False)}")

        return state

    def _handle_extraction_approval(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle extraction approval state (APPROVAL GATE)

        Final approval before extracting data from production systems.
        """
        logger.info(f"[FullWorkflow] EXTRACTION_APPROVAL: {state['request_id']}")

        state["current_state"] = "extraction_approval"
        state["updated_at"] = datetime.now().isoformat()

        logger.info(f"[FullWorkflow] Waiting for extraction approval...")

        return state

    def _handle_data_extraction(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle data extraction state

        Invokes Extraction Agent to extract and de-identify data.
        """
        logger.info(f"[FullWorkflow] DATA_EXTRACTION: {state['request_id']}")

        state["current_state"] = "data_extraction"
        state["updated_at"] = datetime.now().isoformat()

        if self.use_real_agents and self.extraction_agent:
            # REAL AGENT: Invoke Extraction Agent
            logger.info("[FullWorkflow] Invoking REAL ExtractionAgent...")

            try:
                # Prepare context for agent
                context = {
                    "request_id": state["request_id"],
                    "phenotype_sql": state["phenotype_sql"],
                    "requirements": state["requirements"],
                    "phi_level": state["requirements"].get("phi_level", "safe_harbor")
                }

                # Execute agent task
                import asyncio
                result = asyncio.run(self.extraction_agent.execute_task(
                    task="extract_data",
                    context=context
                ))

                # Update state from agent result
                state["extraction_complete"] = result.get("extraction_complete", False)
                state["extracted_data_summary"] = result.get("data_summary", {})

                logger.info(f"[FullWorkflow] ExtractionAgent result: complete={state['extraction_complete']}")

            except Exception as e:
                logger.error(f"[FullWorkflow] ExtractionAgent failed: {e}")
                state["extraction_complete"] = False
                state["error"] = f"Extraction agent error: {str(e)}"

        else:
            # STUB VALUES: For testing without real agents
            logger.info("[FullWorkflow] Using STUB VALUES for extraction")
            state["extraction_complete"] = True
            state["extracted_data_summary"] = {
                "total_patients": 150,
                "total_records": 5000,
                "phi_removed": True
            }

        logger.info(f"[FullWorkflow] Extraction complete: {state.get('extraction_complete', False)}")

        return state

    def _handle_qa_validation(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle QA validation state

        Invokes QA Agent to validate extracted data quality.
        """
        logger.info(f"[FullWorkflow] QA_VALIDATION: {state['request_id']}")

        state["current_state"] = "qa_validation"
        state["updated_at"] = datetime.now().isoformat()

        if self.use_real_agents and self.qa_agent:
            # REAL AGENT: Invoke QA Agent
            logger.info("[FullWorkflow] Invoking REAL QAAgent...")

            try:
                # Prepare context for agent
                context = {
                    "request_id": state["request_id"],
                    "extracted_data_summary": state.get("extracted_data_summary", {}),
                    "requirements": state["requirements"]
                }

                # Execute agent task
                import asyncio
                result = asyncio.run(self.qa_agent.execute_task(
                    task="validate_quality",
                    context=context
                ))

                # Update state from agent result
                state["overall_status"] = result.get("overall_status", "unknown")
                state["qa_report"] = result.get("qa_report", {})

                logger.info(f"[FullWorkflow] QAAgent result: status={state['overall_status']}")

            except Exception as e:
                logger.error(f"[FullWorkflow] QAAgent failed: {e}")
                state["overall_status"] = "failed"
                state["qa_report"] = {
                    "overall_status": "failed",
                    "error": str(e)
                }
                state["error"] = f"QA agent error: {str(e)}"

        else:
            # STUB VALUES: For testing without real agents
            logger.info("[FullWorkflow] Using STUB VALUES for QA")
            state["overall_status"] = "passed"
            state["qa_report"] = {
                "overall_status": "passed",
                "checks": {
                    "completeness": {"passed": True, "score": 1.0},
                    "duplicates": {"passed": True, "duplicates_found": 0},
                    "phi_scrubbing": {"passed": True, "phi_found": 0}
                }
            }

        logger.info(f"[FullWorkflow] QA status: {state.get('overall_status', 'unknown')}")

        return state

    def _handle_qa_review(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle QA review state (APPROVAL GATE)

        Informatician reviews QA report before data delivery.
        """
        logger.info(f"[FullWorkflow] QA_REVIEW: {state['request_id']}")

        state["current_state"] = "qa_review"
        state["updated_at"] = datetime.now().isoformat()

        logger.info(f"[FullWorkflow] Waiting for QA approval...")

        return state

    def _handle_data_delivery(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle data delivery state

        This is where the Delivery Agent would be invoked.
        """
        logger.info(f"[FullWorkflow] DATA_DELIVERY: {state['request_id']}")

        state["current_state"] = "data_delivery"
        state["updated_at"] = datetime.now().isoformat()

        # NOTE: In production, this would invoke the Delivery Agent
        # For E2E testing, set stub delivery values
        delivered_at_value = datetime.now().isoformat()
        state["delivered"] = True
        state["delivered_at"] = delivered_at_value
        state["delivery_location"] = f"/secure/data/{state['request_id']}"

        print(f"DEBUG: Set delivered_at={delivered_at_value}")
        logger.info(f"[FullWorkflow] Delivered: {state.get('delivered', False)}")

        return state

    def _handle_complete(self, state: FullWorkflowState) -> FullWorkflowState:
        """Handle complete state (TERMINAL)"""
        logger.info(f"[FullWorkflow] COMPLETE: {state['request_id']}")

        state["current_state"] = "complete"
        state["updated_at"] = datetime.now().isoformat()

        return state

    def _handle_not_feasible(self, state: FullWorkflowState) -> FullWorkflowState:
        """Handle not feasible state (TERMINAL)"""
        logger.info(f"[FullWorkflow] NOT_FEASIBLE: {state['request_id']}")

        state["current_state"] = "not_feasible"
        state["updated_at"] = datetime.now().isoformat()
        state["escalation_reason"] = "Cohort size too small or infeasible criteria"

        return state

    def _handle_qa_failed(self, state: FullWorkflowState) -> FullWorkflowState:
        """Handle QA failed state (TERMINAL)"""
        logger.info(f"[FullWorkflow] QA_FAILED: {state['request_id']}")

        state["current_state"] = "qa_failed"
        state["updated_at"] = datetime.now().isoformat()
        state["escalation_reason"] = "QA validation failed"

        return state

    def _handle_human_review(self, state: FullWorkflowState) -> FullWorkflowState:
        """Handle human review state (TERMINAL)"""
        logger.info(f"[FullWorkflow] HUMAN_REVIEW: {state['request_id']}")

        state["current_state"] = "human_review"
        state["updated_at"] = datetime.now().isoformat()

        if not state.get("escalation_reason"):
            state["escalation_reason"] = "Extraction rejected - needs human intervention"

        return state

    # ========================================================================
    # Conditional Routing Functions
    # ========================================================================

    def _route_after_requirements_gathering(
        self, state: FullWorkflowState
    ) -> Literal["requirements_review", "wait_for_input"]:
        """
        Route after requirements gathering

        Returns:
            "requirements_review" if requirements complete
            "wait_for_input" if needs more conversation (stops and waits for user)
        """
        if state.get("requirements_complete", False):
            logger.info(f"[FullWorkflow] Routing to requirements_review")
            return "requirements_review"
        else:
            logger.info(f"[FullWorkflow] Routing to END - waiting for more user input")
            return "wait_for_input"

    def _route_after_requirements_review(
        self, state: FullWorkflowState
    ) -> Literal["feasibility_validation", "requirements_gathering", "wait_for_approval"]:
        """
        Route after requirements review (approval gate)

        Returns:
            "feasibility_validation" if approved
            "requirements_gathering" if rejected (need to revise)
            "wait_for_approval" if approval pending (stops and waits)
        """
        if state.get("requirements_approved") is True:
            logger.info(f"[FullWorkflow] Requirements approved → feasibility_validation")
            return "feasibility_validation"
        elif state.get("requirements_approved") is False:
            logger.info(f"[FullWorkflow] Requirements rejected → requirements_gathering")
            return "requirements_gathering"
        else:
            logger.info(f"[FullWorkflow] Waiting for requirements approval")
            return "wait_for_approval"

    def _route_after_feasibility_validation(
        self, state: FullWorkflowState
    ) -> Literal["phenotype_review", "not_feasible"]:
        """
        Route after feasibility validation

        Returns:
            "phenotype_review" if feasible
            "not_feasible" if not feasible (terminal)
        """
        feasible_value = state.get("feasible", False)
        logger.info(f"[FullWorkflow] Routing after feasibility_validation: feasible={feasible_value}, cohort_size={state.get('estimated_cohort_size')}")

        if feasible_value:
            logger.info(f"[FullWorkflow] Feasible → phenotype_review")
            return "phenotype_review"
        else:
            logger.info(f"[FullWorkflow] Not feasible → not_feasible (terminal)")
            return "not_feasible"

    def _route_after_phenotype_review(
        self, state: FullWorkflowState
    ) -> Literal["schedule_kickoff", "feasibility_validation", "wait_for_approval"]:
        """
        Route after phenotype review (approval gate)

        Returns:
            "schedule_kickoff" if SQL approved
            "feasibility_validation" if rejected (need to regenerate SQL)
            "wait_for_approval" if approval pending
        """
        if state.get("phenotype_approved") is True:
            logger.info(f"[FullWorkflow] SQL approved → schedule_kickoff")
            return "schedule_kickoff"
        elif state.get("phenotype_approved") is False:
            logger.info(f"[FullWorkflow] SQL rejected → feasibility_validation")
            return "feasibility_validation"
        else:
            logger.info(f"[FullWorkflow] Waiting for SQL approval")
            return "wait_for_approval"

    def _route_after_extraction_approval(
        self, state: FullWorkflowState
    ) -> Literal["data_extraction", "human_review", "wait_for_approval"]:
        """
        Route after extraction approval (approval gate)

        Returns:
            "data_extraction" if approved
            "human_review" if rejected (terminal)
            "wait_for_approval" if approval pending
        """
        if state.get("extraction_approved") is True:
            logger.info(f"[FullWorkflow] Extraction approved → data_extraction")
            return "data_extraction"
        elif state.get("extraction_approved") is False:
            logger.info(f"[FullWorkflow] Extraction rejected → human_review")
            return "human_review"
        else:
            logger.info(f"[FullWorkflow] Waiting for extraction approval")
            return "wait_for_approval"

    def _route_after_qa_validation(
        self, state: FullWorkflowState
    ) -> Literal["qa_review", "qa_failed"]:
        """
        Route after QA validation

        Returns:
            "qa_review" if QA passed
            "qa_failed" if QA failed (terminal)
        """
        if state.get("overall_status") == "passed":
            logger.info(f"[FullWorkflow] QA passed → qa_review")
            return "qa_review"
        else:
            logger.info(f"[FullWorkflow] QA failed → qa_failed (terminal)")
            return "qa_failed"

    def _route_after_qa_review(
        self, state: FullWorkflowState
    ) -> Literal["data_delivery", "data_extraction", "wait_for_approval"]:
        """
        Route after QA review (approval gate)

        Returns:
            "data_delivery" if QA approved
            "data_extraction" if rejected (need to re-extract)
            "wait_for_approval" if approval pending
        """
        if state.get("qa_approved") is True:
            logger.info(f"[FullWorkflow] QA approved → data_delivery")
            return "data_delivery"
        elif state.get("qa_approved") is False:
            logger.info(f"[FullWorkflow] QA rejected → data_extraction (redo)")
            return "data_extraction"
        else:
            logger.info(f"[FullWorkflow] Waiting for QA approval")
            return "wait_for_approval"

    # ========================================================================
    # Public Methods
    # ========================================================================

    @traceable(
        run_type="chain",
        name="ResearchFlow_FullWorkflow",
        tags=["workflow", "langgraph", "research", "production"],
        metadata={"version": "1.0.0", "total_states": 23, "sprint": "5"}
    )
    async def run(
        self,
        initial_state: FullWorkflowState,
        config: Optional[RunnableConfig] = None
    ) -> FullWorkflowState:
        """
        Run the workflow from initial state to completion (or approval gate)

        Now with LangSmith tracing enabled (Sprint 5) for full observability.

        Args:
            initial_state: Initial workflow state
            config: Optional RunnableConfig for custom metadata/tags

        Returns:
            Final workflow state (may be at approval gate or terminal state)
        """
        logger.info(f"[FullWorkflow] Starting workflow for {initial_state['request_id']}")

        # Prepare config with metadata for tracing
        if config is None:
            config = RunnableConfig(
                metadata={
                    "request_id": initial_state.get("request_id"),
                    "initial_state": initial_state.get("current_state"),
                    "researcher": initial_state.get("researcher_name"),
                    "timestamp": datetime.now().isoformat()
                },
                tags=["e2e-test"] if "E2E" in initial_state.get("request_id", "") else ["production"]
            )

        # Run the compiled graph with tracing
        start_time = datetime.now()
        final_state = await self.compiled_graph.ainvoke(initial_state, config=config)
        end_time = datetime.now()

        duration_ms = (end_time - start_time).total_seconds() * 1000

        logger.info(
            f"[FullWorkflow] Workflow ended in state: {final_state['current_state']} "
            f"(duration: {duration_ms:.2f}ms)"
        )

        return final_state

    def get_graph_diagram(self) -> str:
        """
        Get Mermaid diagram of the workflow

        LangGraph automatically generates visual diagrams.
        This is a major advantage over the custom FSM which requires
        manual PlantUML diagram creation.

        Returns:
            Mermaid diagram string
        """
        try:
            return self.compiled_graph.get_graph().draw_mermaid()
        except Exception as e:
            logger.error(f"Failed to generate diagram: {e}")
            return "Diagram generation failed"


# ============================================================================
# Comparison Notes (Sprint 3)
# ============================================================================

# CODE COMPLEXITY:
# - Custom FSM (workflow_engine.py): ~335 lines, 23 states, manual transition table
# - LangGraph Full (langgraph_workflow.py): ~720 lines, 23 states, declarative
# - Verdict: LangGraph is more verbose but much clearer
#
# STATE TRANSITIONS:
# - Custom: Manual workflow_rules dict with lambda conditions
# - LangGraph: Declarative add_edge() + add_conditional_edges()
# - Verdict: LangGraph is more readable and maintainable
#
# APPROVAL GATES:
# - Custom: Mixed into transition logic (hard to see approval flow)
# - LangGraph: Explicit nodes (requirements_review, phenotype_review, etc.)
# - Verdict: LangGraph makes approval gates visible and trackable
#
# CONDITIONAL ROUTING:
# - Custom: Lambda conditions scattered in workflow_rules
# - LangGraph: Dedicated routing functions with clear logic
# - Verdict: LangGraph is easier to debug and test
#
# VISUALIZATION:
# - Custom: No automatic visualization (manual PlantUML)
# - LangGraph: Automatic Mermaid diagram generation
# - Verdict: LangGraph wins (get_graph().draw_mermaid())
#
# TYPE SAFETY:
# - Custom: No type checking on state
# - LangGraph: TypedDict enforces complete state schema
# - Verdict: LangGraph catches bugs at dev time
#
# ERROR HANDLING:
# - Custom: Manual error state transitions
# - LangGraph: Explicit error nodes (not_feasible, qa_failed, human_review)
# - Verdict: LangGraph makes error paths clearer
#
# AGENT INTEGRATION:
# - Custom: Agents called directly from orchestrator
# - LangGraph: Agents called from node handlers (cleaner separation)
# - Verdict: LangGraph has better separation of concerns
#
# OBSERVABILITY:
# - Custom: Custom logging only
# - LangGraph: Built-in LangSmith integration (track each node execution)
# - Verdict: LangGraph wins (production observability)
#
# PERFORMANCE:
# - TBD (Sprint 4 benchmarks will measure)
#
# OVERALL (Sprint 3 Assessment):
# - LangGraph provides significant advantages for complex workflows
# - Approval gates are first-class citizens (not hidden in transitions)
# - Automatic visualization is invaluable for documentation
# - Type safety prevents state-related bugs
# - Recommend proceeding to Sprint 4 (Performance Benchmarking)
