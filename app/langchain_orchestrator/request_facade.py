"""
Request Facade for UI Compatibility (Phase 3)

Provides a backward-compatible interface that matches ResearchRequestOrchestrator
while internally using LangGraph workflow.

This allows existing Streamlit UIs (researcher_portal.py, admin_dashboard.py)
to work without modification by presenting the same API as the old orchestrator.

Key responsibilities:
1. Present same interface as ResearchRequestOrchestrator
2. Translate orchestrator calls → LangGraph workflow invocations
3. Maintain database records (ResearchRequest, etc.)
4. Handle approval workflow integration

This is a temporary migration layer. Once UIs are updated to use LangGraph directly,
this facade can be removed.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
import asyncio
import uuid

from app.langchain_orchestrator.langgraph_workflow import FullWorkflow
from app.langchain_orchestrator.persistence import get_checkpointer
from app.langchain_orchestrator.approval_bridge import ApprovalBridge
from app.database import get_db_session, ResearchRequest, AuditLog
from sqlalchemy import select

logger = logging.getLogger(__name__)


class LangGraphRequestFacade:
    """
    Facade that presents ResearchRequestOrchestrator interface
    while using LangGraph workflow internally.

    Drop-in replacement for ResearchRequestOrchestrator in UIs.

    Example:
        ```python
        # Old code (orchestrator.py):
        orchestrator = ResearchRequestOrchestrator()

        # New code (with facade):
        orchestrator = LangGraphRequestFacade()

        # Same API works for both!
        request_id = await orchestrator.process_new_request(
            researcher_request="Study request...",
            researcher_info={"name": "Dr. Smith", ...}
        )
        ```
    """

    def __init__(self, use_real_agents: bool = True, use_persistence: bool = True):
        """
        Initialize facade with LangGraph workflow.

        Args:
            use_real_agents: If True, use real agents. If False, use stubs for testing.
            use_persistence: If True, enable LangGraph checkpointing for state persistence.
        """
        self.use_real_agents = use_real_agents
        self.use_persistence = use_persistence

        # Defer workflow initialization until first async call (get_checkpointer is async)
        self.workflow = None
        self._initialized = False

        # Initialize approval bridge for human-in-the-loop workflow
        self.approval_bridge = ApprovalBridge()

        # For compatibility: track "registered" agents (though LangGraph manages them)
        self.agents = {}

        logger.info(
            f"[LangGraphRequestFacade] Initialized (real_agents={use_real_agents}, "
            f"persistence={use_persistence})"
        )

    async def _ensure_initialized(self):
        """
        Lazy initialization of LangGraph workflow (async).

        Must be called at the start of every public async method.
        This is needed because get_checkpointer() is async but __init__ cannot be.
        """
        if self._initialized:
            return

        # Initialize LangGraph workflow with checkpointer and persistence
        from app.langchain_orchestrator.persistence import WorkflowPersistence

        checkpointer = await get_checkpointer() if self.use_persistence else None
        persistence = WorkflowPersistence() if self.use_persistence else None

        self.workflow = FullWorkflow(
            use_real_agents=self.use_real_agents, checkpointer=checkpointer, persistence=persistence
        )
        self._initialized = True

        logger.info(
            f"[LangGraphRequestFacade] Workflow initialized "
            f"(checkpointer={'enabled' if checkpointer else 'disabled'}, "
            f"persistence={'enabled' if persistence else 'disabled'})"
        )

    def register_agent(self, agent_id: str, agent_instance):
        """
        Register an agent (for API compatibility).

        Note: LangGraph workflow internally manages agents, so this is just
        for compatibility with old orchestrator API. The facade doesn't use
        these registered agents.

        Args:
            agent_id: Agent identifier (e.g., "phenotype_agent")
            agent_instance: Agent instance (ignored by facade)
        """
        self.agents[agent_id] = agent_instance
        logger.debug(f"[LangGraphRequestFacade] Registered agent: {agent_id} (for compatibility)")

    async def process_new_request(
        self, researcher_request: str, researcher_info: Dict[str, Any]
    ) -> str:
        """
        Main entry point for new research data request.

        Creates ResearchRequest in database and starts LangGraph workflow.

        Args:
            researcher_request: Natural language request from researcher
            researcher_info: Researcher metadata (name, email, IRB, etc.)

        Returns:
            request_id: Unique identifier for tracking the request

        Example:
            ```python
            request_id = await facade.process_new_request(
                researcher_request="Find diabetes patients age > 50",
                researcher_info={
                    "name": "Dr. Smith",
                    "email": "smith@hospital.org",
                    "department": "Endocrinology",
                    "irb_number": "IRB-2025-001"
                }
            )
            print(f"Created request: {request_id}")
            ```
        """
        # Ensure workflow is initialized (lazy init for async checkpointer)
        await self._ensure_initialized()

        # Generate request ID
        request_id = self._generate_request_id()

        # Create database record for tracking
        async with get_db_session() as session:
            research_request = ResearchRequest(
                id=request_id,
                researcher_name=researcher_info.get("name", "Unknown"),
                researcher_email=researcher_info.get("email", ""),
                researcher_department=researcher_info.get("department"),
                irb_number=researcher_info.get("irb_number"),
                initial_request=researcher_request,
                current_state="new_request",
                current_agent=None,
                agents_involved=[],
                state_history=[{"state": "new_request", "timestamp": datetime.now().isoformat()}],
            )
            session.add(research_request)
            await session.flush()

            # Log to audit trail
            audit_entry = AuditLog(
                request_id=request_id,
                event_type="request_created",
                event_data={
                    "researcher_name": researcher_info.get("name"),
                    "initial_request": researcher_request,
                    "orchestrator": "LangGraphRequestFacade",
                },
                triggered_by="facade",
                severity="info",
            )
            session.add(audit_entry)
            await session.commit()

        logger.info(
            f"[LangGraphRequestFacade] New request {request_id} from "
            f"{researcher_info.get('name', 'Unknown')}"
        )

        # Start LangGraph workflow asynchronously
        # Use asyncio.create_task to run workflow in background
        asyncio.create_task(self._run_workflow(request_id, researcher_request, researcher_info))

        return request_id

    async def _run_workflow(
        self, request_id: str, researcher_request: str, researcher_info: Dict[str, Any]
    ):
        """
        Run LangGraph workflow for a request (internal method).

        This is called asynchronously after process_new_request returns.
        The workflow runs in the background and updates database as it progresses.

        Args:
            request_id: Request identifier
            researcher_request: Natural language request
            researcher_info: Researcher metadata
        """
        try:
            # Ensure workflow is initialized (lazy init for async checkpointer)
            await self._ensure_initialized()

            logger.info(f"[LangGraphRequestFacade] Starting workflow for {request_id}")

            # Create initial state for LangGraph
            initial_state = {
                "request_id": request_id,
                "current_state": "new_request",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                # Researcher info
                "researcher_request": researcher_request,
                "researcher_info": researcher_info,
                # Requirements (to be filled by workflow)
                "requirements": {},
                "requirements_complete": False,
                "completeness_score": 0.0,
                "conversation_history": [],
                "requirements_approved": None,
                "requirements_rejection_reason": None,
                # Feasibility (to be filled by workflow)
                "phenotype_sql": None,
                "feasibility_score": 0.0,
                "estimated_cohort_size": None,
                "feasible": False,
                "phenotype_approved": None,
                "phenotype_rejection_reason": None,
                # Kickoff (to be filled by workflow)
                "meeting_scheduled": False,
                "meeting_details": None,
                # Extraction (to be filled by workflow)
                "extraction_approved": None,
                "extraction_rejection_reason": None,
                "extraction_complete": False,
                "extracted_data_summary": None,
                # QA (to be filled by workflow)
                "overall_status": None,
                "qa_report": None,
                "qa_approved": None,
                "qa_rejection_reason": None,
                # Delivery (to be filled by workflow)
                "delivered": False,
                "delivered_at": None,
                "delivery_location": None,
                "delivery_info": None,
                # Error handling
                "error": None,
                "escalation_reason": None,
                # Scope change
                "scope_change_requested": False,
                "scope_approved": None,
            }

            # Configure LangGraph execution
            config = {"configurable": {"thread_id": request_id}, "recursion_limit": 50}

            # Invoke LangGraph workflow
            final_state = await self.workflow.compiled_graph.ainvoke(initial_state, config=config)

            logger.info(
                f"[LangGraphRequestFacade] Workflow completed for {request_id}, "
                f"final state: {final_state.get('current_state')}"
            )

            # Update database with final state
            await self._update_request_from_state(request_id, final_state)

        except Exception as e:
            logger.error(
                f"[LangGraphRequestFacade] Workflow failed for {request_id}: {e}", exc_info=True
            )

            # Update database with error
            async with get_db_session() as session:
                result = await session.execute(
                    select(ResearchRequest).where(ResearchRequest.id == request_id)
                )
                req = result.scalar_one_or_none()
                if req:
                    req.current_state = "error"
                    req.error_message = str(e)
                    await session.commit()

    async def _update_request_from_state(self, request_id: str, state: Dict[str, Any]):
        """
        Update ResearchRequest database record from LangGraph state.

        Syncs workflow state back to database for UI visibility.

        Args:
            request_id: Request identifier
            state: LangGraph workflow state
        """
        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            req = result.scalar_one_or_none()

            if req:
                req.current_state = state.get("current_state", req.current_state)
                req.updated_at = datetime.now()

                # Update state history if changed
                if state.get("current_state") and state["current_state"] != req.current_state:
                    state_history = req.state_history or []
                    state_history.append(
                        {"state": state["current_state"], "timestamp": datetime.now().isoformat()}
                    )
                    req.state_history = state_history

                await session.commit()

    async def route_task(
        self, agent_id: str, task: str, context: Dict[str, Any], from_agent: str = None
    ):
        """
        Route task to agent (for API compatibility).

        Note: LangGraph handles routing internally, so this method is a no-op.
        Kept for backward compatibility with old orchestrator API.

        In the old orchestrator, this method was used to manually route work
        between agents. With LangGraph, the StateGraph handles routing via
        conditional edges.

        Args:
            agent_id: Target agent (ignored)
            task: Task to execute (ignored)
            context: Task context (ignored)
            from_agent: Source agent (ignored)
        """
        # Ensure workflow is initialized (lazy init for async checkpointer)
        await self._ensure_initialized()

        logger.debug(
            f"[LangGraphRequestFacade] route_task called (ignored): "
            f"{agent_id}.{task} from {from_agent}"
        )
        # No-op: LangGraph handles routing

    async def process_approval_response(
        self,
        approval_id: int,
        reviewer: str,
        decision: str,
        notes: Optional[str] = None,
        modifications: Optional[Dict[str, Any]] = None,
    ):
        """
        Process approval response and continue workflow.

        When admin approves/rejects in UI, this method:
        1. Updates approval record in database
        2. Resumes LangGraph workflow to continue from approval gate

        Args:
            approval_id: Approval record ID
            reviewer: User ID or email of reviewer
            decision: 'approve', 'reject', or 'modify'
            notes: Optional review notes
            modifications: Optional modifications (for modify decision)

        Example:
            ```python
            # Admin approves phenotype SQL in dashboard
            await facade.process_approval_response(
                approval_id=123,
                reviewer="admin@hospital.org",
                decision="approve",
                notes="SQL looks good"
            )
            # Workflow automatically resumes and continues to next step
            ```
        """
        # Ensure workflow is initialized (lazy init for async checkpointer)
        await self._ensure_initialized()

        logger.info(
            f"[LangGraphRequestFacade] Processing approval {approval_id}: "
            f"{decision} by {reviewer}"
        )

        # Map decision to status
        status_map = {"approve": "approved", "reject": "rejected", "modify": "modified"}
        status = status_map.get(decision, "approved")

        # Update approval in database using approval bridge
        success = await self.approval_bridge.update_approval_status(
            approval_id=approval_id,
            status=status,
            reviewed_by=reviewer,
            review_notes=notes,
            modifications=modifications,
        )

        if not success:
            logger.error(f"[LangGraphRequestFacade] Failed to update approval {approval_id}")
            return

        # Get approval to find request_id
        async with get_db_session() as session:
            from app.database.models import Approval

            result = await session.execute(select(Approval).where(Approval.id == approval_id))
            approval = result.scalar_one_or_none()

            if not approval:
                logger.error(f"[LangGraphRequestFacade] Approval {approval_id} not found")
                return

            request_id = approval.request_id
            approval_type = approval.approval_type

        logger.info(
            f"[LangGraphRequestFacade] Approval {approval_id} for {request_id} "
            f"({approval_type}): {decision}"
        )

        # Resume workflow (LangGraph will check approval status and continue)
        # This triggers workflow continuation from the approval gate
        asyncio.create_task(self._resume_workflow_after_approval(request_id, approval_type))

    async def _resume_workflow_after_approval(self, request_id: str, approval_type: str):
        """
        Resume LangGraph workflow after approval decision.

        LangGraph checkpointing allows workflow to resume from where it stopped.

        Args:
            request_id: Request identifier
            approval_type: Type of approval (requirements, phenotype_sql, etc.)
        """
        try:
            # Ensure workflow is initialized (lazy init for async checkpointer)
            await self._ensure_initialized()

            logger.info(
                f"[LangGraphRequestFacade] Resuming workflow for {request_id} "
                f"after {approval_type} approval"
            )

            # Configure LangGraph execution with thread_id for checkpointing
            config = {"configurable": {"thread_id": request_id}, "recursion_limit": 50}

            # Resume workflow from checkpoint
            # LangGraph will load the saved state and continue from approval gate
            final_state = await self.workflow.compiled_graph.ainvoke(
                None, config=config  # State loaded from checkpoint
            )

            logger.info(
                f"[LangGraphRequestFacade] Workflow resumed for {request_id}, "
                f"final state: {final_state.get('current_state')}"
            )

            # Update database with final state
            await self._update_request_from_state(request_id, final_state)

        except Exception as e:
            logger.error(
                f"[LangGraphRequestFacade] Failed to resume workflow for {request_id}: {e}",
                exc_info=True,
            )

    async def get_request_status(self, request_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current status of a request.

        Same implementation as ResearchRequestOrchestrator - queries database.

        Args:
            request_id: Request identifier

        Returns:
            Dict with request status, or None if not found

        Example:
            ```python
            status = await facade.get_request_status("REQ-20250130-ABC123")
            print(f"State: {status['current_state']}")
            print(f"Agent: {status['current_agent']}")
            ```
        """
        # Ensure workflow is initialized (lazy init for async checkpointer)
        await self._ensure_initialized()

        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            research_request = result.scalar_one_or_none()

            if not research_request:
                return None

            return {
                "request_id": request_id,
                "current_state": research_request.current_state,
                "current_agent": research_request.current_agent,
                "started_at": research_request.created_at.isoformat(),
                "completed_at": (
                    research_request.completed_at.isoformat()
                    if research_request.completed_at
                    else None
                ),
                "agents_involved": research_request.agents_involved,
                "state_history": research_request.state_history,
                "researcher_info": {
                    "name": research_request.researcher_name,
                    "email": research_request.researcher_email,
                    "department": research_request.researcher_department,
                    "irb_number": research_request.irb_number,
                },
            }

    async def get_all_active_requests(self) -> list:
        """
        Get all active requests (not completed).

        Same implementation as ResearchRequestOrchestrator - queries database.

        Returns:
            List of request status dicts, ordered by newest first

        Example:
            ```python
            active = await facade.get_all_active_requests()
            print(f"Found {len(active)} active requests")
            for req in active:
                print(f"  {req['request_id']}: {req['current_state']}")
            ```
        """
        # Ensure workflow is initialized (lazy init for async checkpointer)
        await self._ensure_initialized()

        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest)
                .where(ResearchRequest.completed_at.is_(None))
                .order_by(ResearchRequest.created_at.desc())
            )
            active_requests = result.scalars().all()

            # Use asyncio.gather to properly await all status requests
            statuses = await asyncio.gather(
                *[self.get_request_status(req.id) for req in active_requests]
            )
            return statuses

    def get_agent_metrics(self, agent_id: str = None) -> Dict[str, Any]:
        """
        Get metrics for specific agent or all agents (for API compatibility).

        Note: LangGraph workflow manages agents internally, so this returns
        empty dict. Kept for backward compatibility.

        Args:
            agent_id: Optional agent ID to get metrics for

        Returns:
            Dict with agent metrics (empty for facade)
        """
        logger.debug(f"[LangGraphRequestFacade] get_agent_metrics called (returning empty)")
        return {}

    def _generate_request_id(self) -> str:
        """Generate unique request ID"""
        return f"REQ-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

    async def close(self):
        """Cleanup resources"""
        await self.approval_bridge.close()
        logger.info("[LangGraphRequestFacade] Closed")


# ============================================================================
# Helper Functions
# ============================================================================


def create_langgraph_facade(
    use_real_agents: bool = True, use_persistence: bool = True
) -> LangGraphRequestFacade:
    """
    Factory function to create facade instance.

    Args:
        use_real_agents: If True, use real agents. If False, use stubs for testing.
        use_persistence: If True, enable LangGraph checkpointing for state persistence.

    Returns:
        LangGraphRequestFacade instance

    Example:
        ```python
        # In Streamlit UI or API:
        orchestrator = create_langgraph_facade(
            use_real_agents=True,
            use_persistence=True
        )

        # Use exactly like old orchestrator:
        request_id = await orchestrator.process_new_request(...)
        ```
    """
    return LangGraphRequestFacade(use_real_agents=use_real_agents, use_persistence=use_persistence)


# ============================================================================
# Migration Notes (Sprint 6.5)
# ============================================================================

# MIGRATION STRATEGY:
# The facade provides a drop-in replacement for ResearchRequestOrchestrator.
# UIs can switch with a simple import change:
#
# # Old code:
# from app.orchestrator.orchestrator import ResearchRequestOrchestrator
# orchestrator = ResearchRequestOrchestrator()
#
# # New code (with facade):
# from app.langchain_orchestrator.request_facade import create_langgraph_facade
# orchestrator = create_langgraph_facade()
#
# All existing UI code continues to work without modification!
#
# FEATURE FLAG APPROACH:
# Use environment variable to toggle between old and new:
#
# USE_LANGGRAPH = os.getenv("USE_LANGGRAPH", "false").lower() == "true"
#
# if USE_LANGGRAPH:
#     from app.langchain_orchestrator.request_facade import create_langgraph_facade
#     orchestrator = create_langgraph_facade()
# else:
#     from app.orchestrator.orchestrator import ResearchRequestOrchestrator
#     orchestrator = ResearchRequestOrchestrator()
#
# FUTURE CLEANUP:
# Once UIs are fully migrated and tested with LangGraph, this facade can be removed.
# UIs should be updated to use LangGraph workflow directly without the facade layer.
