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

        # BUG #11 PART 13 FIX: Remove workflow caching to fix event loop binding errors
        # Create fresh workflow instance for EVERY request (ensures Lock bound to current loop)
        # Old approach: self.workflow cached → reused across Streamlit reruns → Lock bound to old loop
        # New approach: workflow local variable → recreated per-request → Lock bound to current loop
        self._initialized = False

        # Initialize approval bridge for human-in-the-loop workflow
        # CRITICAL: Pass database URL from environment to use same database as Streamlit UIs
        import os

        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")
        self.approval_bridge = ApprovalBridge(database_url=database_url)

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

        NOTE: Uses singleton checkpointer pattern (Sprint 7 - Nov 2025).
        get_checkpointer() returns a singleton instance that is initialized ONCE
        at module level and reused across all requests. This prevents
        "RuntimeError: threads can only be started once" errors.
        """
        if self._initialized:
            return

        # Import dependencies
        from app.langchain_orchestrator.persistence import WorkflowPersistence, get_checkpointer

        # Store checkpointer factory (returns singleton instance)
        self.checkpointer_factory = get_checkpointer if self.use_persistence else None
        self.persistence = WorkflowPersistence() if self.use_persistence else None

        # Workflow will be created per-request with singleton checkpointer
        # State isolation is achieved via thread_id in config
        self._initialized = True

        logger.info(
            f"[LangGraphRequestFacade] Initialized "
            f"(persistence={'enabled' if self.use_persistence else 'disabled'})"
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
        self,
        researcher_request: str,
        researcher_info: Dict[str, Any],
        from_formal_portal: bool = False,
    ) -> str:
        """
        Main entry point for new research data request.

        Creates ResearchRequest in database and starts LangGraph workflow.

        Args:
            researcher_request: Natural language request from researcher
            researcher_info: Researcher metadata (name, email, IRB, etc.)
            from_formal_portal: If True, request came from formal portal (form-based).
                              If False, request came from exploratory portal (chat-based).
                              This flag helps workflow determine validation mode.

        Returns:
            request_id: Unique identifier for tracking the request

        Example:
            ```python
            # From formal portal (form-based)
            request_id = await facade.process_new_request(
                researcher_request="Find diabetes patients age > 50",
                researcher_info={
                    "name": "Dr. Smith",
                    "email": "smith@hospital.org",
                    "department": "Endocrinology",
                    "irb_number": "IRB-2025-001"
                },
                from_formal_portal=True
            )

            # From exploratory portal (chat-based)
            request_id = await facade.process_new_request(
                researcher_request="Show me diabetes stats",
                researcher_info={"name": "Dr. Smith", "email": "smith@hospital.org"},
                from_formal_portal=False
            )
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

        # Start LangGraph workflow synchronously
        # Execute workflow and wait for completion (UI already has timeout)
        await self._run_workflow(
            request_id, researcher_request, researcher_info, from_formal_portal
        )

        return request_id

    async def _ensure_db_record_exists(self, request_id: str, initial_state: Dict[str, Any]):
        """
        CRITICAL: Create ResearchRequest in PostgreSQL before workflow starts.

        ApprovalBridge requires this for FK constraints when creating approvals.
        Without this, requests exist only in LangGraph checkpoints (split-brain condition).

        This fixes the issue where:
        1. LangGraph workflow runs and stores state in SQLite checkpoints
        2. NO ResearchRequest record exists in PostgreSQL
        3. ApprovalBridge.create_approval_request() fails FK constraint check
        4. Admin Dashboard shows empty requirements (reads from PostgreSQL, not checkpoints)

        Args:
            request_id: Request identifier
            initial_state: Initial LangGraph workflow state
        """
        async with get_db_session() as session:
            # Check if already exists
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                logger.debug(
                    f"[RequestFacade] ResearchRequest {request_id} already exists in PostgreSQL"
                )
                return  # Already synced

            # Create new record from initial state
            request = ResearchRequest(
                id=request_id,
                researcher_name=initial_state["researcher_info"].get("name"),
                researcher_email=initial_state["researcher_info"].get("email"),
                researcher_department=initial_state["researcher_info"].get("department"),
                initial_request=initial_state["researcher_request"],
                current_state=initial_state["current_state"],
                created_at=datetime.fromisoformat(initial_state["created_at"]),
                updated_at=datetime.now(),
            )

            session.add(request)
            await session.commit()
            logger.info(
                f"[RequestFacade] Created ResearchRequest in PostgreSQL: {request_id}"
                f"\n  This ensures ApprovalBridge can create approvals (FK constraint)"
                f"\n  Prevents split-brain where request exists in checkpoints but not main DB"
            )

    async def _run_workflow(
        self,
        request_id: str,
        researcher_request: str,
        researcher_info: Dict[str, Any],
        from_formal_portal: bool = False,
    ):
        """
        Run LangGraph workflow for a request (internal method).

        This is called asynchronously after process_new_request returns.
        The workflow runs in the background and updates database as it progresses.

        Args:
            request_id: Request identifier
            researcher_request: Natural language request
            researcher_info: Researcher metadata
            from_formal_portal: Whether request came from formal portal (form-based) or exploratory (chat-based)
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
                "from_formal_portal": from_formal_portal,  # Form-based vs chat-based validation
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

            # CRITICAL: Ensure request exists in PostgreSQL before workflow starts
            # This prevents split-brain where request exists in checkpoints but not main DB
            # ApprovalBridge requires this for FK constraints when creating approvals
            await self._ensure_db_record_exists(request_id, initial_state)

            # CRITICAL FIX: Use singleton checkpointer (Sprint 7 - Nov 2025)
            # Singleton pattern prevents "RuntimeError: threads can only be started once"
            # The checkpointer is entered ONCE at module level and reused across all requests
            if self.checkpointer_factory:
                # Get singleton checkpointer (already initialized, no context manager needed)
                checkpointer = await self.checkpointer_factory()

                logger.info(
                    f"[Singleton Checkpointer] Using singleton checkpointer for request {request_id}"
                    f"\n  Checkpointer instance ID: {id(checkpointer)}"
                    f"\n  Checkpointer type: {type(checkpointer).__name__}"
                    f"\n  Thread ID (for state isolation): {request_id}"
                )

                # Import FullWorkflow here to avoid circular import
                from app.langchain_orchestrator.langgraph_workflow import FullWorkflow

                # BUG #11 PART 13 FIX: Create fresh workflow for THIS request (not cached)
                # This ensures Lock in checkpointer is bound to CURRENT event loop
                # State isolation is achieved via thread_id in config
                workflow = FullWorkflow(
                    use_real_agents=self.use_real_agents,
                    checkpointer=checkpointer,
                    persistence=self.persistence,
                )

                # Execute workflow with real-time state synchronization
                # Use astream_events to get updates after each node execution
                final_state = None
                last_synced_state = None
                async for event in workflow.compiled_graph.astream_events(
                    initial_state, config, version="v2"
                ):
                    # Process events from workflow execution
                    if event["event"] == "on_chain_end":
                        # Get current state from event output
                        current_state = event.get("data", {}).get("output", {})
                        # Check if this is a valid state dict with current_state field
                        if (
                            current_state
                            and isinstance(current_state, dict)
                            and "current_state" in current_state
                        ):
                            # Only update if state has changed
                            if current_state.get("current_state") != last_synced_state:
                                # Update database with current state
                                await self._update_request_from_state(request_id, current_state)
                                last_synced_state = current_state.get("current_state")
                                logger.info(
                                    f"[LangGraphRequestFacade] State updated: {current_state.get('current_state', 'unknown')}"
                                )
                            final_state = current_state

                # If no final state captured from events, fallback to invoke
                if final_state is None:
                    logger.warning(
                        "[LangGraphRequestFacade] No state captured from events, falling back to ainvoke"
                    )
                    final_state = await workflow.compiled_graph.ainvoke(initial_state, config)
                    await self._update_request_from_state(request_id, final_state)

                logger.info(
                    f"[Singleton Checkpointer] Workflow completed for request {request_id} (checkpointer instance {id(checkpointer)} will be reused)"
                )
            else:
                # No persistence - create workflow without checkpointer
                from app.langchain_orchestrator.langgraph_workflow import FullWorkflow

                # BUG #11 PART 13 FIX: Create fresh workflow for THIS request (not cached)
                workflow = FullWorkflow(
                    use_real_agents=self.use_real_agents, checkpointer=None, persistence=None
                )

                # Execute workflow with real-time state synchronization
                final_state = None
                last_synced_state = None
                async for event in workflow.compiled_graph.astream_events(
                    initial_state, config, version="v2"
                ):
                    if event["event"] == "on_chain_end":
                        current_state = event.get("data", {}).get("output", {})
                        # Check if this is a valid state dict with current_state field
                        if (
                            current_state
                            and isinstance(current_state, dict)
                            and "current_state" in current_state
                        ):
                            # Only update if state has changed
                            if current_state.get("current_state") != last_synced_state:
                                await self._update_request_from_state(request_id, current_state)
                                last_synced_state = current_state.get("current_state")
                                logger.info(
                                    f"[LangGraphRequestFacade] State updated: {current_state.get('current_state', 'unknown')}"
                                )
                            final_state = current_state

                if final_state is None:
                    logger.warning(
                        "[LangGraphRequestFacade] No state captured from events, falling back to ainvoke"
                    )
                    final_state = await workflow.compiled_graph.ainvoke(initial_state, config)
                    await self._update_request_from_state(request_id, final_state)

            logger.info(
                f"[LangGraphRequestFacade] Workflow completed for {request_id}, "
                f"final state: {final_state.get('current_state') if final_state else 'unknown'}"
            )

        except Exception as e:
            logger.error(
                f"[LangGraphRequestFacade] Workflow FAILED for {request_id}: {e}", exc_info=True
            )

            # Update database with error (ENHANCED: track workflow attempt and provide debugging info)
            async with get_db_session() as session:
                result = await session.execute(
                    select(ResearchRequest).where(ResearchRequest.id == request_id)
                )
                req = result.scalar_one_or_none()
                if req:
                    req.current_state = "error"
                    req.error_message = str(e)
                    req.updated_at = datetime.now()

                    # Track workflow execution attempt in agents_involved for debugging
                    agents_involved = req.agents_involved or []
                    agents_involved.append(
                        {
                            "agent": "langgraph_workflow",
                            "task": "_run_workflow",
                            "timestamp": datetime.now().isoformat(),
                            "error": str(e),
                            "error_type": type(e).__name__,
                        }
                    )
                    req.agents_involved = agents_involved

                    # Update state history
                    state_history = req.state_history or []
                    state_history.append(
                        {
                            "state": "error",
                            "timestamp": datetime.now().isoformat(),
                            "error": str(e),
                        }
                    )
                    req.state_history = state_history

                    await session.commit()

                    logger.info(
                        f"[LangGraphRequestFacade] Updated {request_id} with error state. "
                        f"Check agents_involved for details."
                    )

    def _get_agent_for_state(self, current_state: str) -> Optional[str]:
        """
        Map workflow state to the agent responsible for that state.

        Args:
            current_state: Current workflow state name

        Returns:
            Agent ID string or None if no agent is active for this state
        """
        STATE_TO_AGENT = {
            "new_request": None,
            "requirements_gathering": "requirements_agent",
            "requirements_review": "requirements_agent",
            "feasibility_validation": "phenotype_agent",
            "phenotype_review": "phenotype_agent",
            # NEW: Preview extraction workflow
            "preview_extraction": "extraction_agent",
            "preview_qa": "qa_agent",
            "preview_qa_review": "qa_agent",
            # Full extraction (after preview)
            "data_extraction": "extraction_agent",
            "qa_validation": "qa_agent",
            "qa_review": "qa_agent",
            "data_delivery": "delivery_agent",
            # Calendar scheduling (optional, moved to after delivery)
            "schedule_kickoff": "calendar_agent",
            "kickoff_scheduled": "calendar_agent",
            "delivered": "delivery_agent",
            "complete": None,
            "failed": None,
            "not_feasible": None,
            "qa_failed": None,
            "human_review": None,
        }
        return STATE_TO_AGENT.get(current_state)

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
                req.current_agent = self._get_agent_for_state(state.get("current_state"))
                req.updated_at = datetime.now()

                # Update state history if changed
                if state.get("current_state") and state["current_state"] != req.current_state:
                    state_history = req.state_history or []
                    state_history.append(
                        {"state": state["current_state"], "timestamp": datetime.now().isoformat()}
                    )
                    req.state_history = state_history

                await session.commit()
            else:
                # Request not found in database - split-brain condition detected
                logger.error(
                    f"[LangGraphRequestFacade] CRITICAL: Cannot update state for {request_id} - "
                    f"request not found in database!"
                )
                logger.error(f"  Current LangGraph state: {state.get('current_state')}")
                logger.error(f"  Requirements complete: {state.get('requirements_complete')}")
                logger.error(f"  Feasible: {state.get('feasible')}")
                logger.error(
                    f"  This indicates the request was never created in the main database or was deleted. "
                    f"The request may exist in LangGraph checkpoints but not in PostgreSQL (split-brain)."
                )

    async def route_task(
        self, agent_id: str, task: str, context: Dict[str, Any], from_agent: str = None
    ):
        """
        Route task to agent (for API compatibility).

        ⚠️ IMPORTANT LIMITATION: This method is a no-op with LangGraph.

        LangGraph handles routing internally via StateGraph conditional edges,
        so manual routing is not supported. This method exists only for backward
        compatibility with old orchestrator API.

        **Known Impact**:
        - **Preview Approval Feature**: Admin dashboard's "preview approval" workflow
          calls `route_task()` to trigger full extraction after preview (line 534).
          This will NOT work with LangGraph - the task will be silently ignored.

        **Workaround**:
        - Use custom orchestrator for requests requiring preview approval
        - Or remove preview approval feature from admin dashboard when using LangGraph
        - Or implement workflow resume using checkpointer (future enhancement)

        In the old orchestrator, this method was used to manually route work
        between agents. With LangGraph, the StateGraph handles routing via
        conditional edges and cannot be manually triggered mid-workflow.

        Args:
            agent_id: Target agent (ignored)
            task: Task to execute (ignored)
            context: Task context (ignored)
            from_agent: Source agent (ignored)

        Returns:
            None (no-op)
        """
        # Ensure workflow is initialized (lazy init for async checkpointer)
        await self._ensure_initialized()

        logger.warning(
            f"[LangGraphRequestFacade] route_task called but IGNORED: "
            f"{agent_id}.{task} from {from_agent}. "
            f"LangGraph does not support manual routing. "
            f"Preview approval feature will not work."
        )
        # No-op: LangGraph handles routing via StateGraph conditional edges

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
        # IMPORTANT: Run synchronously (not background task) to ensure it completes
        # before Streamlit reruns the page
        await self._resume_workflow_after_approval(request_id, approval_type)

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

            # BUG #11 PART 13 FIX: Always create fresh workflow for THIS resume (not cached)
            # This ensures Lock in checkpointer is bound to CURRENT event loop
            # Old approach: if self.workflow is None → cached workflow → Lock bound to old loop
            # New approach: always create workflow → recreated per-resume → Lock bound to current loop
            from app.langchain_orchestrator.langgraph_workflow import FullWorkflow

            if self.use_persistence:
                checkpointer = await self.checkpointer_factory()
                workflow = FullWorkflow(
                    use_real_agents=self.use_real_agents,
                    checkpointer=checkpointer,
                    persistence=self.persistence,
                )
            else:
                workflow = FullWorkflow(
                    use_real_agents=self.use_real_agents, checkpointer=None, persistence=None
                )

            logger.info(
                f"[LangGraphRequestFacade] Resuming workflow for {request_id} "
                f"after {approval_type} approval"
            )

            # Configure LangGraph execution with thread_id for checkpointing
            config = {"configurable": {"thread_id": request_id}, "recursion_limit": 50}

            # Resume workflow from checkpoint
            # LangGraph will load the saved state and continue from approval gate
            #
            # Bug #11 Part 7 fix: Use astream_events for real-time state updates during resumption
            # This ensures database is updated as workflow progresses through nodes
            # (same pattern as _run_workflow initial execution)
            final_state = None
            last_synced_state = None

            async for event in workflow.compiled_graph.astream_events(None, config, version="v2"):
                # Process events from workflow execution
                if event["event"] == "on_chain_end":
                    # Get current state from event output
                    current_state = event.get("data", {}).get("output", {})
                    # Check if this is a valid state dict with current_state field
                    if (
                        current_state
                        and isinstance(current_state, dict)
                        and "current_state" in current_state
                    ):
                        # Only update if state has changed
                        if current_state.get("current_state") != last_synced_state:
                            # Update database with current state
                            await self._update_request_from_state(request_id, current_state)
                            last_synced_state = current_state.get("current_state")
                            logger.info(
                                f"[LangGraphRequestFacade] State updated during resumption: "
                                f"{current_state.get('current_state', 'unknown')}"
                            )
                        final_state = current_state

            # If no final state captured from events, fallback to invoke
            if final_state is None:
                logger.warning(
                    f"[LangGraphRequestFacade] No state captured from resumption events for {request_id}, "
                    f"falling back to ainvoke"
                )
                final_state = await workflow.compiled_graph.ainvoke(None, config)
                await self._update_request_from_state(request_id, final_state)

            logger.info(
                f"[LangGraphRequestFacade] Workflow resumed for {request_id}, "
                f"final state: {final_state.get('current_state')}"
            )

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

    async def get_all_active_requests(self, include_completed: bool = False) -> list:
        """
        Get all active requests, ordered by newest first.

        Same implementation as ResearchRequestOrchestrator - queries database.

        Args:
            include_completed: If True, includes completed requests. Default False for backward compatibility.

        Returns:
            List of request status dicts, ordered by newest first

        Example:
            ```python
            # Get only active requests
            active = await facade.get_all_active_requests()
            print(f"Found {len(active)} active requests")

            # Get all requests including completed
            all_requests = await facade.get_all_active_requests(include_completed=True)
            print(f"Found {len(all_requests)} total requests")

            for req in active:
                print(f"  {req['request_id']}: {req['current_state']}")
            ```
        """
        # Ensure workflow is initialized (lazy init for async checkpointer)
        await self._ensure_initialized()

        async with get_db_session() as session:
            query = select(ResearchRequest)

            # Filter out completed requests unless explicitly requested
            if not include_completed:
                query = query.where(ResearchRequest.completed_at.is_(None))

            query = query.order_by(ResearchRequest.created_at.desc())  # Newest first

            result = await session.execute(query)
            active_requests = result.scalars().all()

            # Use asyncio.gather to properly await all status requests
            statuses = await asyncio.gather(
                *[self.get_request_status(req.id) for req in active_requests]
            )
            return statuses

    async def get_approval_history(self, request_id: str) -> list:
        """
        Get all approval history for a request.

        Same implementation as ResearchRequestOrchestrator - queries Approval table.

        Args:
            request_id: Request identifier

        Returns:
            List of approval dicts with status, timestamps, reviewer info

        Example:
            ```python
            history = await facade.get_approval_history("REQ-20250110-ABC123")
            for approval in history:
                print(f"{approval['approval_type']}: {approval['status']}")
                print(f"  Reviewed by {approval['reviewed_by']} at {approval['reviewed_at']}")
            ```
        """
        # Ensure workflow is initialized (lazy init for async checkpointer)
        await self._ensure_initialized()

        async with get_db_session() as session:
            from app.database.models import Approval

            result = await session.execute(
                select(Approval)
                .where(Approval.request_id == request_id)
                .order_by(Approval.submitted_at.asc())
            )
            approvals = result.scalars().all()

            return [
                {
                    "approval_type": approval.approval_type,
                    "submitted_at": (
                        approval.submitted_at.isoformat() if approval.submitted_at else None
                    ),
                    "submitted_by": approval.submitted_by,
                    "status": approval.status,
                    "reviewed_at": (
                        approval.reviewed_at.isoformat() if approval.reviewed_at else None
                    ),
                    "reviewed_by": approval.reviewed_by,
                    "review_notes": approval.review_notes,
                }
                for approval in approvals
            ]

    async def get_requests_by_researcher(self, researcher_email: str) -> list:
        """
        Get all requests for a specific researcher, ordered by newest first.

        Enables researchers to view their own request history in the researcher portal.
        This is a facade method that queries the database directly (not workflow state).

        Args:
            researcher_email: Researcher email to filter by

        Returns:
            List of request status dicts for matching researcher, ordered by newest first

        Example:
            researcher_requests = await facade.get_requests_by_researcher("researcher@example.com")
            # Returns: [
            #   {"request_id": "REQ-123", "status": "complete", "created_at": "...", ...},
            #   {"request_id": "REQ-456", "status": "qa_review", "created_at": "...", ...},
            # ]
        """
        # Ensure workflow is initialized (lazy init for async checkpointer)
        await self._ensure_initialized()

        from app.database import get_db_session
        from app.database.models import ResearchRequest
        from sqlalchemy import select
        import asyncio

        logger.info(f"[LangGraphRequestFacade] Getting requests for researcher: {researcher_email}")

        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest)
                .where(ResearchRequest.researcher_email == researcher_email)
                .order_by(ResearchRequest.created_at.desc())  # Newest first
            )
            researcher_requests = result.scalars().all()

            logger.info(
                f"[LangGraphRequestFacade] Found {len(researcher_requests)} requests for {researcher_email}"
            )

            # Use asyncio.gather to properly await all status requests
            # This reuses get_request_status() to build full status dicts
            statuses = await asyncio.gather(
                *[self.get_request_status(req.id) for req in researcher_requests]
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
