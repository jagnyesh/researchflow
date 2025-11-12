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
from app.agents.requirements_agent import RequirementsAgent
from app.agents.phenotype_agent import PhenotypeValidationAgent
from app.agents.calendar_agent import CalendarAgent
from app.agents.extraction_agent import DataExtractionAgent
from app.agents.qa_agent import QualityAssuranceAgent
from app.agents.delivery_agent import DeliveryAgent

# Import ApprovalBridge for database sync at approval gates
from app.langchain_orchestrator.approval_bridge import (
    create_approval_from_state,
    check_approval_status,
)

# Import database models for AgentExecution tracking
from app.database import get_db_session, AgentExecution, DATABASE_URL
from sqlalchemy import select

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
    sql_parameters: dict | None  # SQL parameters for parameterized queries
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

    # ===== Preview Extraction Phase ===== (NEW - Sprint X)
    preview_extracted: bool
    preview_package: dict | None
    preview_qa_passed: bool  # Auto-approval flag for preview QA
    preview_qa_report: dict | None
    preview_qa_review_approved: bool | None  # Human approval if preview QA fails
    preview_qa_rejection_reason: str | None

    # ===== QA Phase =====
    overall_status: str | None  # 'passed', 'failed'
    qa_report: dict | None
    qa_approved: bool | None  # NOTE: Used for DELIVERY approval (not QA)
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

    # ===== Request Source =====
    from_formal_portal: bool  # True = form-based validation, False = chat-based


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

    def __init__(self, use_real_agents: bool = False, checkpointer=None, persistence=None):
        """
        Initialize the full workflow graph

        Args:
            use_real_agents: If True, invoke real agents instead of stubs.
                            If False (default), use stub values for testing.
            checkpointer: Optional AsyncSqliteSaver singleton instance.
                         Use get_checkpointer() to obtain the singleton instance.
                         If provided, enables workflow state snapshots and resumption.
            persistence: Optional WorkflowPersistence instance for database sync.
                        If provided, state will be automatically saved to main database
                        after each workflow run.

        Note:
            The graph is compiled immediately in __init__ with the provided checkpointer.
            Uses singleton pattern (Sprint 7 - Nov 2025) to prevent threading errors.

        Example:
            ```python
            # CORRECT: Use singleton checkpointer (Sprint 7 - Nov 2025)
            checkpointer = await get_checkpointer()  # Returns singleton instance
            workflow = FullWorkflow(use_real_agents=True, checkpointer=checkpointer)
            config = {"configurable": {"thread_id": "REQ-123"}}
            result = await workflow.compiled_graph.ainvoke(state, config)

            # MULTIPLE REQUESTS: Same checkpointer, different thread_ids for isolation
            checkpointer1 = await get_checkpointer()  # Same instance
            workflow1 = FullWorkflow(checkpointer=checkpointer1)
            config1 = {"configurable": {"thread_id": "REQ-123"}}

            checkpointer2 = await get_checkpointer()  # Same instance as checkpointer1
            workflow2 = FullWorkflow(checkpointer=checkpointer2)
            config2 = {"configurable": {"thread_id": "REQ-456"}}  # Different thread_id = isolated state
            ```
        """
        self.use_real_agents = use_real_agents
        self.checkpointer = checkpointer
        self.persistence = persistence

        # Initialize real agents if requested
        if use_real_agents:
            logger.info("[FullWorkflow] Initializing with REAL AGENTS")

            # Get HAPI FHIR database URL from environment
            # Default uses asyncpg for async connections
            hapi_db_url = os.getenv(
                "HAPI_DB_URL",
                "postgresql+asyncpg://hapi:hapi@localhost:5433/hapi",  # pragma: allowlist secret
            )
            healthcare_db_url = os.getenv("HEALTHCARE_DB_URL")

            logger.info(f"[FullWorkflow] HAPI DB URL: {hapi_db_url}")
            logger.info(f"[FullWorkflow] Healthcare DB URL: {healthcare_db_url}")

            # Initialize all 6 agents with appropriate database connections
            self.requirements_agent = RequirementsAgent()
            self.phenotype_agent = PhenotypeValidationAgent(database_url=hapi_db_url)
            self.calendar_agent = CalendarAgent()
            self.extraction_agent = DataExtractionAgent(
                database_url=healthcare_db_url or hapi_db_url
            )
            self.qa_agent = QualityAssuranceAgent()
            self.delivery_agent = DeliveryAgent()
        else:
            logger.info("[FullWorkflow] Initializing with STUB VALUES (test mode)")
            self.requirements_agent = None
            self.phenotype_agent = None
            self.calendar_agent = None
            self.extraction_agent = None
            self.qa_agent = None
            self.delivery_agent = None

        self.graph = self._build_graph()
        # Compile with checkpointer if provided (enables persistence)
        # IMPORTANT: interrupt_after pauses workflow AFTER approval nodes execute
        # This allows nodes to create approval requests BEFORE pausing
        # Using interrupt_before would prevent nodes from executing and creating approvals
        self.compiled_graph = self.graph.compile(
            checkpointer=self.checkpointer,
            interrupt_after=[
                "requirements_review",  # Pause after requirements approval node (approval created)
                "phenotype_review",  # Pause after phenotype SQL approval node (approval created)
                "preview_qa_review",  # Pause after preview QA approval node (approval created) - NEW
                "qa_review",  # Pause after full extraction QA approval node (approval created)
            ],
        )

        persistence_mode = "WITH PERSISTENCE" if self.checkpointer else "WITHOUT PERSISTENCE"
        logger.info(f"[FullWorkflow] Initialized with 23 states ({persistence_mode})")

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
        # NEW: Preview extraction workflow nodes
        graph.add_node("preview_extraction", self._handle_preview_extraction)
        graph.add_node("preview_qa", self._handle_preview_qa)
        graph.add_node("preview_qa_review", self._handle_preview_qa_review)
        # Full extraction (after preview passes)
        graph.add_node("data_extraction", self._handle_data_extraction)
        # Calendar scheduling (optional, moved to after delivery)
        graph.add_node("schedule_kickoff", self._handle_schedule_kickoff)
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
        # → feasibility_validation (if form-based submission, skip requirements review)
        # → requirements_review (if chat-based submission and complete)
        # → END (if needs more conversation)
        graph.add_conditional_edges(
            "requirements_gathering",
            self._route_after_requirements_gathering,
            {
                "requirements_review": "requirements_review",
                "feasibility_validation": "feasibility_validation",
                "wait_for_input": END,
            },
        )

        # 2. After requirements_review (approval gate)
        # → feasibility_validation (if approved)
        # → requirements_gathering (if rejected)
        # Note: "wait_for_approval" route removed - workflow now uses interrupt_after
        graph.add_conditional_edges(
            "requirements_review",
            self._route_after_requirements_review,
            {
                "feasibility_validation": "feasibility_validation",
                "requirements_gathering": "requirements_gathering",
                # "wait_for_approval": END,  # Removed - handled by interrupt_after
            },
        )

        # 3. After feasibility_validation
        # → phenotype_review (if feasible)
        # → not_feasible (if not feasible)
        graph.add_conditional_edges(
            "feasibility_validation",
            self._route_after_feasibility_validation,
            {"phenotype_review": "phenotype_review", "not_feasible": "not_feasible"},
        )

        # 4. After phenotype_review (approval gate)
        # → preview_extraction (if approved) - NEW: Extract 10 rows per data element
        # → not_feasible (if rejected as infeasible by human)
        # → feasibility_validation (if rejected for revision)
        # Note: "wait_for_approval" route removed - workflow now uses interrupt_after
        graph.add_conditional_edges(
            "phenotype_review",
            self._route_after_phenotype_review,
            {
                "preview_extraction": "preview_extraction",  # UPDATED: Go to preview first, not schedule_kickoff
                "not_feasible": "not_feasible",
                "feasibility_validation": "feasibility_validation",
                # "wait_for_approval": END,  # Removed - handled by interrupt_after
            },
        )

        # 4a. After preview_extraction (NEW)
        # → preview_qa (always) - Auto QA validation on preview data
        graph.add_edge("preview_extraction", "preview_qa")

        # 4b. After preview_qa (NEW)
        # → data_extraction (if preview QA passed - auto-approve)
        # → preview_qa_review (if preview QA failed - requires approval)
        graph.add_conditional_edges(
            "preview_qa",
            self._route_after_preview_qa,
            {
                "data_extraction": "data_extraction",  # Preview passed - proceed to full extraction
                "preview_qa_review": "preview_qa_review",  # Preview failed - human review
            },
        )

        # 4c. After preview_qa_review (approval gate) (NEW)
        # → data_extraction (if approved despite QA failure)
        # → feasibility_validation (if rejected - revise SQL)
        graph.add_conditional_edges(
            "preview_qa_review",
            self._route_after_preview_qa_review,
            {
                "data_extraction": "data_extraction",
                "feasibility_validation": "feasibility_validation",
            },
        )

        # 5. After data_extraction (FULL extraction, not preview)
        # → qa_validation (always)
        graph.add_edge("data_extraction", "qa_validation")

        # 6. After qa_validation
        # → qa_review (if passed)
        # → qa_failed (if failed)
        graph.add_conditional_edges(
            "qa_validation",
            self._route_after_qa_validation,
            {"qa_review": "qa_review", "qa_failed": "qa_failed"},
        )

        # 7. After qa_review (approval gate)
        # → data_delivery (if approved)
        # → data_extraction (if rejected - redo extraction)
        # Note: "wait_for_approval" route removed - workflow now uses interrupt_after
        graph.add_conditional_edges(
            "qa_review",
            self._route_after_qa_review,
            {
                "data_delivery": "data_delivery",
                "data_extraction": "data_extraction",
                # "wait_for_approval": END,  # Removed - handled by interrupt_after
            },
        )

        # 8. After data_delivery
        # → schedule_kickoff (optional - post-delivery meeting) OR complete
        graph.add_conditional_edges(
            "data_delivery",
            self._route_after_data_delivery,
            {
                "schedule_kickoff": "schedule_kickoff",  # Optional post-delivery meeting
                "complete": "complete",  # Skip meeting, go straight to complete
            },
        )

        # 9. After schedule_kickoff (OPTIONAL - now happens after delivery)
        # → complete (always)
        graph.add_edge("schedule_kickoff", "complete")

        # ===== Terminal States → END =====
        graph.add_edge("complete", END)
        graph.add_edge("not_feasible", END)
        graph.add_edge("qa_failed", END)
        graph.add_edge("human_review", END)

        return graph

    # ========================================================================
    # State Handlers (Node Functions)
    # ========================================================================

    async def _handle_new_request(self, state: FullWorkflowState) -> FullWorkflowState:
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
        if "sql_parameters" not in state:
            state["sql_parameters"] = (
                {}
            )  # Initialize SQL parameters dict (Sprint X - SQL Parameters Bug Fix)
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

        # Initialize preview extraction fields (NEW - Sprint X)
        if "preview_extracted" not in state:
            state["preview_extracted"] = False
        if "preview_qa_passed" not in state:
            state["preview_qa_passed"] = False

        return state

    async def _track_agent_execution_start(
        self, request_id: str, agent_id: str, task: str, context: dict
    ) -> Optional[int]:
        """
        Create AgentExecution record at task start.

        Returns the execution ID for later updates.
        """
        try:
            async with get_db_session() as session:
                execution = AgentExecution(
                    request_id=request_id,
                    agent_id=agent_id,
                    task=task,
                    started_at=datetime.now(),
                    status="running",
                    context=context,
                )
                session.add(execution)
                await session.commit()
                await session.refresh(execution)
                logger.info(
                    f"[AgentTracking] Started tracking: {agent_id}/{task} (ID: {execution.id})"
                )
                return execution.id
        except Exception as e:
            logger.error(f"[AgentTracking] Failed to track execution start: {e}")
            return None

    async def _track_agent_execution_complete(
        self, execution_id: Optional[int], status: str, result: dict = None, error: str = None
    ):
        """
        Update AgentExecution record at task completion.
        """
        if execution_id is None:
            return

        try:
            async with get_db_session() as session:
                exec_result = await session.execute(
                    select(AgentExecution).where(AgentExecution.id == execution_id)
                )
                execution = exec_result.scalar_one_or_none()
                if execution:
                    execution.completed_at = datetime.now()
                    execution.status = status
                    if execution.started_at:
                        execution.duration_seconds = (
                            datetime.now() - execution.started_at
                        ).total_seconds()
                    if result:
                        execution.result = result
                    if error:
                        execution.error = error
                    await session.commit()
                    logger.info(
                        f"[AgentTracking] Completed tracking: ID {execution_id} with status {status}"
                    )
        except Exception as e:
            logger.error(f"[AgentTracking] Failed to track execution complete: {e}")

    async def _handle_requirements_gathering(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle requirements gathering state

        Invokes Requirements Agent to extract structured requirements from researcher request.
        """
        logger.info(f"[FullWorkflow] REQUIREMENTS_GATHERING: {state['request_id']}")

        state["current_state"] = "requirements_gathering"
        state["updated_at"] = datetime.now().isoformat()

        if self.use_real_agents and self.requirements_agent:
            # REAL AGENT: Invoke Requirements Agent
            logger.info("[FullWorkflow] Invoking REAL RequirementsAgent...")

            # Prepare context for agent (matching RequirementsAgent interface)
            context = {
                "request_id": state["request_id"],
                "initial_request": state["researcher_request"],  # Agent expects "initial_request"
                "researcher_info": state["researcher_info"],
                "conversation_history": state.get("conversation_history", []),
                "from_formal_portal": state.get(
                    "from_formal_portal", False
                ),  # Required for validation
            }

            # Track agent execution start
            execution_id = await self._track_agent_execution_start(
                state["request_id"], "requirements_agent", "gather_requirements", context
            )

            try:
                # Execute agent task (async call - non-blocking)
                result = await self.requirements_agent.execute_task(
                    task="gather_requirements",
                    context=context,  # Agent expects "gather_requirements"
                )

                # Update state from agent result
                state["requirements"] = result.get(
                    "structured_requirements", {}
                )  # Agent returns "structured_requirements"
                state["requirements_complete"] = result.get("requirements_complete", False)
                state["completeness_score"] = result.get("completeness_score", 0.0)

                # Update conversation history if agent added responses
                if "conversation_history" in result:
                    state["conversation_history"] = result["conversation_history"]

                logger.info(
                    f"[FullWorkflow] RequirementsAgent result: complete={state['requirements_complete']}, score={state['completeness_score']:.1%}"
                )

                # Track agent execution success
                await self._track_agent_execution_complete(execution_id, "success", result)

            except Exception as e:
                logger.error(f"[FullWorkflow] RequirementsAgent failed: {e}")
                # Track agent execution failure
                await self._track_agent_execution_complete(execution_id, "failed", error=str(e))

                # Fall back to conservative defaults on error
                state["requirements"] = {}
                state["requirements_complete"] = False
                state["completeness_score"] = 0.0
                state["error"] = f"Requirements agent error: {str(e)}"

        else:
            # STUB VALUES: For E2E testing without real agents
            logger.info("[FullWorkflow] Using STUB requirements (test mode)")

            # Extract basic requirements from researcher_request if possible
            researcher_request = state.get("researcher_request", "")

            # Create stub requirements based on common patterns
            stub_requirements = {
                "inclusion_criteria": ["Patients matching the described criteria"],
                "exclusion_criteria": [],
                "data_elements": ["Demographics", "Clinical data as requested"],
                "time_period": "All available data",
                "phi_level": "safe_harbor",
            }

            state["requirements"] = stub_requirements
            state["requirements_complete"] = True  # Mark complete to allow workflow progression
            state["completeness_score"] = 1.0

        logger.info(
            f"[FullWorkflow] Requirements complete: {state.get('requirements_complete', False)}"
        )

        return state

    async def _handle_requirements_review(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle requirements review state (APPROVAL GATE)

        This is a human-in-the-loop approval gate.
        Workflow pauses here until informatician approves/rejects requirements.
        """
        logger.info(f"[FullWorkflow] REQUIREMENTS_REVIEW: {state['request_id']}")

        state["current_state"] = "requirements_review"
        state["updated_at"] = datetime.now().isoformat()

        # Create approval request if not exists
        if state.get("requirements_approved") is None:
            logger.info(f"[FullWorkflow] Creating requirements approval request in database...")
            await create_approval_from_state(
                state["request_id"], "requirements", state, database_url=DATABASE_URL
            )

        # Check for approval decision from database
        logger.info(f"[FullWorkflow] Checking for requirements approval decision...")
        state = await check_approval_status(
            state["request_id"], "requirements", state, database_url=DATABASE_URL
        )

        logger.info(
            f"[FullWorkflow] Requirements approved: {state.get('requirements_approved', 'pending')}"
        )

        return state

    async def _handle_feasibility_validation(self, state: FullWorkflowState) -> FullWorkflowState:
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

            # Prepare context for agent
            context = {
                "request_id": state["request_id"],
                "requirements": state["requirements"],
                "researcher_info": state["researcher_info"],
            }

            # Track agent execution start
            execution_id = await self._track_agent_execution_start(
                state["request_id"], "phenotype_agent", "validate_feasibility", context
            )

            try:
                # Execute agent task (async call - non-blocking)
                result = await self.phenotype_agent.execute_task(
                    task="validate_feasibility", context=context
                )

                # Update state from agent result
                state["feasible"] = result.get("feasible", False)
                state["estimated_cohort_size"] = result.get("estimated_cohort_size")
                state["phenotype_sql"] = result.get("phenotype_sql")
                # Extract SQL parameters from approval_data (Sprint X - SQL Parameters Bug Fix)
                approval_data = result.get("additional_context", {}).get("approval_data", {})
                state["sql_parameters"] = approval_data.get("parameters", {})
                state["feasibility_score"] = result.get("feasibility_score", 0.0)
                state["feasibility_report"] = result.get(
                    "feasibility_report", {}
                )  # Store detailed report

                logger.info(
                    f"[FullWorkflow] PhenotypeAgent result: feasible={state['feasible']}, cohort={state['estimated_cohort_size']}"
                )

                # Track agent execution success
                await self._track_agent_execution_complete(execution_id, "success", result)

            except Exception as e:
                logger.error(f"[FullWorkflow] PhenotypeAgent failed: {e}")
                # Track agent execution failure
                await self._track_agent_execution_complete(execution_id, "failed", error=str(e))

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

        logger.info(
            f"[FullWorkflow] Feasibility AFTER: {state.get('feasible', False)} (cohort: {state.get('estimated_cohort_size', 0)})"
        )

        return state

    async def _handle_phenotype_review(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle phenotype review state (APPROVAL GATE)

        Informatician reviews generated SQL query before execution.
        """
        logger.info(f"[FullWorkflow] PHENOTYPE_REVIEW: {state['request_id']}")

        state["current_state"] = "phenotype_review"
        state["updated_at"] = datetime.now().isoformat()

        # Create approval request if not exists
        if state.get("phenotype_approved") is None:
            logger.info(f"[FullWorkflow] Creating phenotype approval request in database...")
            await create_approval_from_state(
                state["request_id"], "phenotype_sql", state, database_url=DATABASE_URL
            )

        # Check for approval decision from database
        logger.info(f"[FullWorkflow] Checking for phenotype approval decision...")
        state = await check_approval_status(
            state["request_id"], "phenotype_sql", state, database_url=DATABASE_URL
        )

        logger.info(
            f"[FullWorkflow] Phenotype approved: {state.get('phenotype_approved', 'pending')}"
        )

        return state

    async def _handle_preview_extraction(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle preview extraction state (NEW)

        Invokes Extraction Agent to extract 10 rows per data element for validation.
        """
        logger.info(f"[FullWorkflow] PREVIEW_EXTRACTION: {state['request_id']}")

        state["current_state"] = "preview_extraction"
        state["current_agent"] = "extraction_agent"
        state["updated_at"] = datetime.now().isoformat()

        if self.use_real_agents and self.extraction_agent:
            # REAL AGENT: Invoke Extraction Agent for preview
            logger.info("[FullWorkflow] Invoking REAL ExtractionAgent for preview (10 rows)...")

            # Prepare context for agent
            context = {
                "request_id": state["request_id"],
                "structured_requirements": state["requirements"],
                "phenotype_sql": state["phenotype_sql"],
                "sql_query": state["phenotype_sql"],  # Alias
                "parameters": state.get(
                    "sql_parameters", {}
                ),  # FIXED: Read from state (Sprint X - SQL Parameters Bug Fix)
            }

            # Track agent execution start
            execution_id = await self._track_agent_execution_start(
                state["request_id"], "extraction_agent", "extract_preview", context
            )

            try:
                # Execute agent task (async call - non-blocking)
                result = await self.extraction_agent.execute_task(
                    task="extract_preview", context=context
                )

                # Update state from agent result
                state["preview_extracted"] = result.get("preview_extracted", False)
                state["preview_package"] = result.get("preview_package", {})

                logger.info(
                    f"[FullWorkflow] ExtractionAgent preview result: extracted={state['preview_extracted']}"
                )

                # Track agent execution success
                await self._track_agent_execution_complete(execution_id, "success", result)

            except Exception as e:
                logger.error(f"[FullWorkflow] ExtractionAgent preview failed: {e}")
                # Track agent execution failure
                await self._track_agent_execution_complete(execution_id, "failed", error=str(e))

                # Fall back to defaults on error
                state["preview_extracted"] = False
                state["preview_package"] = {}
                state["error"] = f"Preview extraction error: {str(e)}"

        else:
            # STUB VALUES: For E2E testing without real agents
            logger.info("[FullWorkflow] Using STUB VALUES for preview extraction")
            state["preview_extracted"] = True
            state["preview_package"] = {
                "cohort": [{"patient_id": "test-123"}],
                "preview_data": {"demographics": [{"name": "Test Patient"}]},
                "metadata": {"is_preview": True, "preview_rows_per_element": 10},
            }

        return state

    async def _handle_preview_qa(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle preview QA state (NEW)

        Invokes QA Agent to validate preview data (cohort count check).
        Auto-approves if cohort count matches estimate (±10%).
        """
        logger.info(f"[FullWorkflow] PREVIEW_QA: {state['request_id']}")

        state["current_state"] = "preview_qa"
        state["current_agent"] = "qa_agent"
        state["updated_at"] = datetime.now().isoformat()

        if self.use_real_agents and self.qa_agent:
            # REAL AGENT: Invoke QA Agent for preview validation
            logger.info("[FullWorkflow] Invoking REAL QAAgent for preview validation...")

            # Prepare context for agent
            context = {
                "request_id": state["request_id"],
                "structured_requirements": state["requirements"],
                "preview_package": state["preview_package"],
                "estimated_cohort": state.get("estimated_cohort_size", 0),
            }

            # Track agent execution start
            execution_id = await self._track_agent_execution_start(
                state["request_id"], "qa_agent", "validate_preview", context
            )

            try:
                # Execute agent task (async call - non-blocking)
                result = await self.qa_agent.execute_task(task="validate_preview", context=context)

                # Update state from agent result
                state["preview_qa_passed"] = result.get("preview_qa_passed", False)
                state["preview_qa_report"] = result.get("qa_report", {})

                logger.info(
                    f"[FullWorkflow] QAAgent preview result: passed={state['preview_qa_passed']}"
                )

                # Track agent execution success
                await self._track_agent_execution_complete(execution_id, "success", result)

            except Exception as e:
                logger.error(f"[FullWorkflow] QAAgent preview validation failed: {e}")
                # Track agent execution failure
                await self._track_agent_execution_complete(execution_id, "failed", error=str(e))

                # Fall back to defaults on error
                state["preview_qa_passed"] = False
                state["preview_qa_report"] = {}
                state["error"] = f"Preview QA error: {str(e)}"

        else:
            # STUB VALUES: For E2E testing without real agents
            logger.info("[FullWorkflow] Using STUB VALUES for preview QA")
            state["preview_qa_passed"] = True
            state["preview_qa_report"] = {"overall_status": "passed", "checks": []}

        return state

    async def _handle_preview_qa_review(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle preview QA review state (APPROVAL GATE) (NEW)

        Human reviews preview QA failure before deciding to proceed or reject.
        """
        logger.info(f"[FullWorkflow] PREVIEW_QA_REVIEW: {state['request_id']}")

        state["current_state"] = "preview_qa_review"
        state["updated_at"] = datetime.now().isoformat()

        # Create approval request if not exists
        if state.get("preview_qa_review_approved") is None:
            logger.info(
                f"[FullWorkflow] Creating preview QA review approval request in database..."
            )
            await create_approval_from_state(
                state["request_id"], "preview_qa", state, database_url=DATABASE_URL  # Approval type
            )

        # Check for approval decision from database
        logger.info(f"[FullWorkflow] Checking for preview QA review approval decision...")
        state = await check_approval_status(
            state["request_id"],
            "preview_qa",  # Maps to preview_qa_review_approved via approval bridge
            state,
            database_url=DATABASE_URL,
        )

        logger.info(
            f"[FullWorkflow] Preview QA review approved: {state.get('preview_qa_review_approved', 'pending')}"
        )

        return state

    async def _handle_schedule_kickoff(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle schedule kickoff state

        Invokes Calendar Agent to schedule kickoff meeting with stakeholders.
        """
        logger.info(f"[FullWorkflow] SCHEDULE_KICKOFF: {state['request_id']}")

        state["current_state"] = "schedule_kickoff"
        state["updated_at"] = datetime.now().isoformat()

        if self.use_real_agents and self.calendar_agent:
            # REAL AGENT: Invoke Calendar Agent
            logger.info("[FullWorkflow] Invoking REAL CalendarAgent...")

            # Prepare context for agent (matching CalendarAgent interface)
            context = {
                "request_id": state["request_id"],
                "requirements": state["requirements"],
                "feasibility_report": {  # Agent expects nested structure
                    "estimated_cohort_size": state.get("estimated_cohort_size"),
                    "feasibility_score": state.get("feasibility_score", 0.0),
                    "warnings": [],  # Add warnings if available in state
                },
            }

            # Track agent execution start
            execution_id = await self._track_agent_execution_start(
                state["request_id"], "calendar_agent", "schedule_kickoff_meeting", context
            )

            try:
                # Execute agent task (async call - non-blocking)
                result = await self.calendar_agent.execute_task(
                    task="schedule_kickoff_meeting",
                    context=context,  # Agent expects "schedule_kickoff_meeting"
                )

                # Update state from agent result
                state["meeting_scheduled"] = result.get("meeting_scheduled", False)
                state["meeting_details"] = result.get(
                    "meeting"
                )  # Agent returns "meeting", not "meeting_details"

                logger.info(
                    f"[FullWorkflow] CalendarAgent result: scheduled={state['meeting_scheduled']}"
                )

                # Track agent execution success
                await self._track_agent_execution_complete(execution_id, "success", result)

            except Exception as e:
                logger.error(f"[FullWorkflow] CalendarAgent failed: {e}")
                # Track agent execution failure
                await self._track_agent_execution_complete(execution_id, "failed", error=str(e))

                # Fall back to defaults on error
                state["meeting_scheduled"] = False
                state["meeting_details"] = None
                state["error"] = f"Calendar agent error: {str(e)}"

        else:
            # STUB VALUES: For E2E testing without real agents
            logger.info("[FullWorkflow] Using STUB meeting scheduling (test mode)")

            # Create stub meeting details
            state["meeting_scheduled"] = True  # Mark scheduled to allow workflow progression
            state["meeting_details"] = {
                "scheduled_at": datetime.now().isoformat(),
                "meeting_time": "TBD - to be scheduled by data team",
                "attendees": ["researcher", "data team"],
            }

        logger.info(f"[FullWorkflow] Meeting scheduled: {state.get('meeting_scheduled', False)}")

        return state

    async def _handle_data_extraction(self, state: FullWorkflowState) -> FullWorkflowState:
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

            # Prepare context for agent
            context = {
                "request_id": state["request_id"],
                "phenotype_sql": state["phenotype_sql"],
                "sql_query": state["phenotype_sql"],  # Agent prefers this key name
                "parameters": state.get(
                    "sql_parameters", {}
                ),  # SQL parameters for bound queries (Sprint X - SQL Parameters Bug Fix)
                "requirements": state["requirements"],
                "phi_level": state["requirements"].get("phi_level", "safe_harbor"),
            }

            # Track agent execution start
            execution_id = await self._track_agent_execution_start(
                state["request_id"], "extraction_agent", "extract_data", context
            )

            try:
                # Execute agent task (async call - non-blocking)
                result = await self.extraction_agent.execute_task(
                    task="extract_data", context=context
                )

                # Update state from agent result
                state["extraction_complete"] = result.get("extraction_complete", False)
                state["extracted_data_summary"] = result.get(
                    "data_package", {}
                )  # Agent returns "data_package"

                logger.info(
                    f"[FullWorkflow] ExtractionAgent result: complete={state['extraction_complete']}"
                )

                # Track agent execution success
                await self._track_agent_execution_complete(execution_id, "success", result)

            except Exception as e:
                logger.error(f"[FullWorkflow] ExtractionAgent failed: {e}")
                # Track agent execution failure
                await self._track_agent_execution_complete(execution_id, "failed", error=str(e))

                state["extraction_complete"] = False
                state["error"] = f"Extraction agent error: {str(e)}"

        else:
            # STUB VALUES: For testing without real agents
            logger.info("[FullWorkflow] Using STUB VALUES for extraction")
            state["extraction_complete"] = True
            state["extracted_data_summary"] = {
                "total_patients": 150,
                "total_records": 5000,
                "phi_removed": True,
            }

        logger.info(
            f"[FullWorkflow] Extraction complete: {state.get('extraction_complete', False)}"
        )

        return state

    async def _handle_qa_validation(self, state: FullWorkflowState) -> FullWorkflowState:
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

            # Prepare context for agent (matching QAAgent interface)
            context = {
                "request_id": state["request_id"],
                "data_package": state.get(
                    "extracted_data_summary", {}
                ),  # Agent expects "data_package"
                "structured_requirements": state[
                    "requirements"
                ],  # Agent expects "structured_requirements"
            }

            # Track agent execution start
            execution_id = await self._track_agent_execution_start(
                state["request_id"], "qa_agent", "validate_extracted_data", context
            )

            try:
                # Execute agent task (async call - non-blocking)
                result = await self.qa_agent.execute_task(
                    task="validate_extracted_data", context=context
                )  # Agent expects "validate_extracted_data"

                # Update state from agent result
                state["overall_status"] = result.get("overall_status", "unknown")
                state["qa_report"] = result.get("qa_report", {})

                logger.info(f"[FullWorkflow] QAAgent result: status={state['overall_status']}")

                # Track agent execution success
                await self._track_agent_execution_complete(execution_id, "success", result)

            except Exception as e:
                logger.error(f"[FullWorkflow] QAAgent failed: {e}")
                # Track agent execution failure
                await self._track_agent_execution_complete(execution_id, "failed", error=str(e))

                state["overall_status"] = "failed"
                state["qa_report"] = {"overall_status": "failed", "error": str(e)}
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
                    "phi_scrubbing": {"passed": True, "phi_found": 0},
                },
            }

        logger.info(f"[FullWorkflow] QA status: {state.get('overall_status', 'unknown')}")

        return state

    async def _handle_qa_review(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle QA review state (APPROVAL GATE)

        Informatician reviews QA report before data delivery.
        """
        logger.info(f"[FullWorkflow] QA_REVIEW: {state['request_id']}")

        state["current_state"] = "qa_review"
        state["updated_at"] = datetime.now().isoformat()

        # Create approval request if not exists
        if state.get("qa_approved") is None:
            logger.info(f"[FullWorkflow] Creating QA approval request in database...")
            await create_approval_from_state(
                state["request_id"], "qa", state, database_url=DATABASE_URL
            )

        # Check for approval decision from database
        logger.info(f"[FullWorkflow] Checking for QA approval decision...")
        state = await check_approval_status(
            state["request_id"], "qa", state, database_url=DATABASE_URL
        )

        logger.info(f"[FullWorkflow] QA approved: {state.get('qa_approved', 'pending')}")

        return state

    async def _handle_data_delivery(self, state: FullWorkflowState) -> FullWorkflowState:
        """
        Handle data delivery state

        Invokes Delivery Agent to package and deliver data to researcher.
        """
        logger.info(f"[FullWorkflow] DATA_DELIVERY: {state['request_id']}")

        state["current_state"] = "data_delivery"
        state["updated_at"] = datetime.now().isoformat()

        if self.use_real_agents and self.delivery_agent:
            # REAL AGENT: Invoke Delivery Agent
            logger.info("[FullWorkflow] Invoking REAL DeliveryAgent...")

            # Prepare context for agent (matching DeliveryAgent interface)
            context = {
                "request_id": state["request_id"],
                "requirements": state["requirements"],
                "researcher_info": state["researcher_info"],
                "data_package": state.get("extracted_data_summary"),  # Agent expects "data_package"
                "qa_report": state.get("qa_report"),
            }

            # Track agent execution start
            execution_id = await self._track_agent_execution_start(
                state["request_id"], "delivery_agent", "deliver_data", context
            )

            try:
                # Execute agent task (async call - non-blocking)
                result = await self.delivery_agent.execute_task(
                    task="deliver_data", context=context
                )

                # Update state from agent result
                state["delivered"] = result.get("delivered", False)
                state["delivered_at"] = result.get("delivered_at")
                state["delivery_location"] = result.get("delivery_location")
                state["delivery_info"] = result.get("delivery_info")

                logger.info(
                    f"[FullWorkflow] DeliveryAgent result: delivered={state['delivered']}, location={state['delivery_location']}"
                )

                # Track agent execution success
                await self._track_agent_execution_complete(execution_id, "success", result)

            except Exception as e:
                logger.error(f"[FullWorkflow] DeliveryAgent failed: {e}")
                # Track agent execution failure
                await self._track_agent_execution_complete(execution_id, "failed", error=str(e))

                # Fall back to defaults on error
                state["delivered"] = False
                state["delivered_at"] = None
                state["delivery_location"] = None
                state["error"] = f"Delivery agent error: {str(e)}"

        else:
            # STUB VALUES: For E2E testing without real agents
            logger.info("[FullWorkflow] Using STUB delivery (test mode)")

            delivered_at_value = datetime.now().isoformat()
            state["delivered"] = True
            state["delivered_at"] = delivered_at_value
            state["delivery_location"] = f"/secure/data/{state['request_id']}"
            state["delivery_info"] = {
                "format": "CSV",
                "file_count": 1,
                "notification_sent": True,
            }

        logger.info(f"[FullWorkflow] Delivered: {state.get('delivered', False)}")

        return state

    async def _handle_complete(self, state: FullWorkflowState) -> FullWorkflowState:
        """Handle complete state (TERMINAL)"""
        logger.info(f"[FullWorkflow] COMPLETE: {state['request_id']}")

        state["current_state"] = "complete"
        state["updated_at"] = datetime.now().isoformat()

        return state

    async def _handle_not_feasible(self, state: FullWorkflowState) -> FullWorkflowState:
        """Handle not feasible state (TERMINAL)"""
        logger.info(f"[FullWorkflow] NOT_FEASIBLE: {state['request_id']}")

        state["current_state"] = "not_feasible"
        state["updated_at"] = datetime.now().isoformat()
        state["escalation_reason"] = "Cohort size too small or infeasible criteria"

        return state

    async def _handle_qa_failed(self, state: FullWorkflowState) -> FullWorkflowState:
        """Handle QA failed state (TERMINAL)"""
        logger.info(f"[FullWorkflow] QA_FAILED: {state['request_id']}")

        state["current_state"] = "qa_failed"
        state["updated_at"] = datetime.now().isoformat()
        state["escalation_reason"] = "QA validation failed"

        return state

    async def _handle_human_review(self, state: FullWorkflowState) -> FullWorkflowState:
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
    ) -> Literal["requirements_review", "feasibility_validation", "wait_for_input"]:
        """
        Route after requirements gathering (matches custom orchestrator behavior)

        For form-based submissions from formal portal, skip requirements approval
        and go straight to SQL generation (phenotype agent). This matches the
        original workflow where SQL approval is the FIRST approval gate.

        For chat-based submissions from exploratory portal, require requirements review.

        Returns:
            "feasibility_validation" if form-based submission (skip requirements review)
            "requirements_review" if chat-based and requirements complete
            "wait_for_input" if needs more conversation (stops and waits for user)
        """
        if state.get("requirements_complete", False):
            # FORM-BASED MODE: Skip requirements review, go straight to SQL generation
            # This matches the original behavior where SQL is the FIRST approval gate
            if state.get("from_formal_portal", False):
                logger.info(
                    f"[FullWorkflow] Form-based submission detected - "
                    f"skipping requirements review, routing to feasibility_validation (SQL generation)"
                )
                return "feasibility_validation"
            # CHAT-BASED MODE: Require requirements review (exploratory portal)
            else:
                logger.info(
                    f"[FullWorkflow] Chat-based submission - routing to requirements_review"
                )
                return "requirements_review"
        else:
            logger.info(f"[FullWorkflow] Routing to END - waiting for more user input")
            return "wait_for_input"

    def _route_after_requirements_review(
        self, state: FullWorkflowState
    ) -> Literal["feasibility_validation", "requirements_gathering"]:
        """
        Route after requirements review (approval gate)

        Returns:
            "feasibility_validation" if approved (or approval pending - interrupted by interrupt_after)
            "requirements_gathering" if rejected (need to revise)

        Note: When approval is pending (requirements_approved=None), returns "feasibility_validation" as default.
              The interrupt_after mechanism will pause before executing feasibility_validation.
              When workflow resumes, this node re-executes and routes based on actual approval decision.
        """
        if state.get("requirements_approved") is True:
            logger.info(f"[FullWorkflow] Requirements approved → feasibility_validation")
            return "feasibility_validation"
        elif state.get("requirements_approved") is False:
            logger.info(f"[FullWorkflow] Requirements rejected → requirements_gathering")
            return "requirements_gathering"
        else:
            # Approval pending - return default route (interrupt_after will pause execution)
            logger.info(
                f"[FullWorkflow] Approval pending → feasibility_validation (will be interrupted)"
            )
            return "feasibility_validation"

    def _route_after_feasibility_validation(
        self, state: FullWorkflowState
    ) -> Literal["phenotype_review", "not_feasible"]:
        """
        Route after feasibility validation

        ALWAYS route to phenotype_review for human approval.
        The informatician decides whether SQL is appropriate to run,
        regardless of automated feasibility metrics (cohort size, data availability).

        This matches the original custom orchestrator behavior where:
        - SQL is ALWAYS shown for human review
        - Informatician can approve low-cohort requests if scientifically valid
        - "Not feasible" only after explicit human rejection

        Returns:
            "phenotype_review" - always (human must approve/reject SQL)
        """
        # Log automated metrics for informatician's reference
        feasible_value = state.get("feasible", False)
        cohort_size = state.get("estimated_cohort_size", 0)
        score = state.get("feasibility_score", 0.0)

        logger.info(
            f"[FullWorkflow] Routing after feasibility_validation: "
            f"auto_feasible={feasible_value}, cohort={cohort_size}, score={score:.2f}"
        )
        logger.info(
            f"[FullWorkflow] Routing to phenotype_review for human SQL approval "
            f"(matches original orchestrator - always show SQL regardless of score)"
        )

        # ALWAYS route to human approval (removed conditional auto-rejection)
        return "phenotype_review"

    def _route_after_phenotype_review(
        self, state: FullWorkflowState
    ) -> Literal["preview_extraction", "feasibility_validation", "not_feasible"]:
        """
        Route after phenotype review (approval gate)

        Human informatician reviews SQL and decides:
        - Approve: Proceed to preview extraction (NEW - extract 10 rows first)
        - Reject as not feasible: Route to not_feasible terminal state
        - Reject for revision: Return to feasibility_validation for SQL regeneration

        Returns:
            "preview_extraction" if SQL approved (or approval pending - interrupted by interrupt_after)
            "not_feasible" if rejected as infeasible by human
            "feasibility_validation" if rejected for revision (need to regenerate SQL)

        Note: When approval is pending (phenotype_approved=None), returns "preview_extraction" as default.
              The interrupt_after mechanism will pause before executing preview_extraction.
              When workflow resumes, this node re-executes and routes based on actual approval decision.
        """
        phenotype_approved = state.get("phenotype_approved")

        if phenotype_approved is True:
            logger.info(f"[FullWorkflow] SQL approved → preview_extraction (extract 10 rows)")
            return "preview_extraction"

        elif phenotype_approved is False:
            # Check rejection reason to determine routing
            rejection_reason = state.get("phenotype_rejection_reason", "").lower()

            # If human explicitly marks as "not feasible", route to terminal state
            if (
                "not feasible" in rejection_reason
                or "cohort too small" in rejection_reason
                or "infeasible" in rejection_reason
            ):
                logger.info(
                    f"[FullWorkflow] SQL rejected as not feasible by human → not_feasible terminal state"
                )
                return "not_feasible"
            else:
                # Rejected for revision (SQL needs improvement, but request is potentially feasible)
                logger.info(f"[FullWorkflow] SQL rejected for revision → feasibility_validation")
                return "feasibility_validation"

        else:
            # Approval pending - return default route (interrupt_after will pause execution)
            logger.info(
                f"[FullWorkflow] Approval pending → preview_extraction (will be interrupted)"
            )
            return "preview_extraction"

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
    ) -> Literal["data_delivery", "data_extraction"]:
        """
        Route after QA review (approval gate)

        Returns:
            "data_delivery" if QA approved (or approval pending - interrupted by interrupt_after)
            "data_extraction" if rejected (need to re-extract)

        Note: When approval is pending (qa_approved=None), returns "data_delivery" as default.
              The interrupt_after mechanism will pause before executing data_delivery.
              When workflow resumes, this node re-executes and routes based on actual approval decision.
        """
        if state.get("qa_approved") is True:
            logger.info(f"[FullWorkflow] QA approved → data_delivery")
            return "data_delivery"
        elif state.get("qa_approved") is False:
            logger.info(f"[FullWorkflow] QA rejected → data_extraction (redo)")
            return "data_extraction"
        else:
            # Approval pending - return default route (interrupt_after will pause execution)
            logger.info(f"[FullWorkflow] Approval pending → data_delivery (will be interrupted)")
            return "data_delivery"

    def _route_after_preview_qa(
        self, state: FullWorkflowState
    ) -> Literal["data_extraction", "preview_qa_review"]:
        """
        Route after preview QA validation (NEW)

        Auto-approves if preview QA passes (cohort count matches ±10%).
        Creates approval if preview QA fails (requires human review).

        Returns:
            "data_extraction" if preview QA passed (auto-approve)
            "preview_qa_review" if preview QA failed (requires approval)
        """
        if state.get("preview_qa_passed") is True:
            logger.info(f"[FullWorkflow] Preview QA passed → data_extraction (auto-approved)")
            return "data_extraction"
        else:
            logger.info(f"[FullWorkflow] Preview QA failed → preview_qa_review (requires approval)")
            return "preview_qa_review"

    def _route_after_preview_qa_review(
        self, state: FullWorkflowState
    ) -> Literal["data_extraction", "feasibility_validation"]:
        """
        Route after preview QA review (approval gate) (NEW)

        Human reviews preview QA failure and decides:
        - Approve: Proceed despite QA failure
        - Reject: Revise SQL and re-extract

        Returns:
            "data_extraction" if approved (proceed despite failure)
            "feasibility_validation" if rejected (revise SQL)
        """
        if state.get("preview_qa_review_approved") is True:
            logger.info(f"[FullWorkflow] Preview QA failure approved → data_extraction")
            return "data_extraction"
        else:
            logger.info(
                f"[FullWorkflow] Preview QA failure rejected → feasibility_validation (revise SQL)"
            )
            return "feasibility_validation"

    def _route_after_data_delivery(
        self, state: FullWorkflowState
    ) -> Literal["schedule_kickoff", "complete"]:
        """
        Route after data delivery (NEW)

        Determines if post-delivery meeting should be scheduled (optional).

        Returns:
            "schedule_kickoff" if calendar meeting enabled
            "complete" if skip meeting
        """
        # Check if calendar scheduling is enabled (optional feature)
        schedule_meeting = state.get("schedule_post_delivery_meeting", False)

        if schedule_meeting:
            logger.info(f"[FullWorkflow] Scheduling post-delivery meeting → schedule_kickoff")
            return "schedule_kickoff"
        else:
            logger.info(f"[FullWorkflow] Skipping post-delivery meeting → complete")
            return "complete"

    # ========================================================================
    # Public Methods
    # ========================================================================

    @traceable(
        run_type="chain",
        name="ResearchFlow_FullWorkflow",
        tags=["workflow", "langgraph", "research", "production"],
        metadata={"version": "1.0.0", "total_states": 23, "sprint": "5"},
    )
    async def run(
        self, initial_state: FullWorkflowState, config: Optional[RunnableConfig] = None
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
                    "timestamp": datetime.now().isoformat(),
                },
                tags=(
                    ["e2e-test"] if "E2E" in initial_state.get("request_id", "") else ["production"]
                ),
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

        # Automatically save state to database if persistence is configured
        if self.persistence:
            try:
                await self.persistence.save_workflow_state(final_state)
                logger.info(
                    f"[FullWorkflow] State saved to database: "
                    f"{final_state['request_id']} → {final_state['current_state']}"
                )
            except Exception as e:
                logger.error(f"[FullWorkflow] Failed to save state to database: {e}", exc_info=True)
                # Don't fail workflow if persistence fails
                # Checkpointer still has state even if DB sync fails

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
