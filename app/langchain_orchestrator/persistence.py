"""
LangGraph Workflow Persistence (Sprint 3 + Sprint 6.5)

This module provides two complementary persistence mechanisms:

1. **LangGraph Native Checkpointing** (Sprint 6.5 - NEW)
   - Uses AsyncSqliteSaver for workflow state snapshots
   - Enables automatic state recovery and resumption
   - Stores state in data/langgraph_checkpoints.db

2. **Database Model Conversion** (Sprint 3 - EXISTING)
   - Bidirectional conversion between LangGraph state and SQLAlchemy models
   - Enables integration with existing ResearchRequest schema
   - Stores state in main application database

Purpose: Enable workflow state persistence, resumption, and database integration
Status: Sprint 6.5 - Migration to LangGraph orchestration
"""

import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

# LangGraph checkpointing imports
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..database.models import (
    ResearchRequest,
    RequirementsData,
    FeasibilityReport,
    AgentExecution,
    Approval,
    DataDelivery,
)
from .langgraph_workflow import FullWorkflowState

logger = logging.getLogger(__name__)


# ============================================================================
# LangGraph Native Checkpointing (Sprint 6.5 - NEW)
# ============================================================================

DEFAULT_CHECKPOINT_DB = "data/langgraph_checkpoints.db"

# ============================================================================
# Singleton Checkpointer Pattern (Sprint 7 - Nov 2025)
# ============================================================================
# CRITICAL FIX: Use singleton pattern to prevent "threads can only be started once" error
#
# AsyncSqliteSaver creates a background thread on context manager entry (__aenter__).
# Streamlit reruns would try to re-enter the context manager, causing:
#   RuntimeError: threads can only be started once
#
# Solution: Enter the context manager ONCE at module level, reuse the instance.
# This ensures the background thread is created once and shared across all requests.

_checkpointer_instance: Optional[AsyncSqliteSaver] = None
_checkpointer_context_manager = None  # Keep reference to prevent premature cleanup
_checkpointer_creation_loop_id: Optional[int] = None  # Track which loop created checkpointer

# BUG #11 PART 11 FIX: Use threading.Lock instead of asyncio.Lock
# threading.Lock is NOT bound to event loops, so it's safe across Streamlit reruns
# This prevents race conditions in checkpointer recreation
import threading

_checkpointer_mutex = threading.Lock()


async def get_checkpointer() -> AsyncSqliteSaver:
    """
    Get singleton LangGraph checkpointer for state persistence (shared across all requests).

    Creates SQLite database at data/langgraph_checkpoints.db with schema:
    - checkpoints table (thread_id, checkpoint_id, state BLOB)
    - writes table (checkpoint_id, task_id, channel, value)

    This enables:
    - Automatic state snapshots after each node execution
    - Workflow resumption from last checkpoint on failure
    - State isolation per thread_id (request_id)

    IMPORTANT: Returns a SINGLETON instance that is shared across all workflow executions.
    The context manager is entered ONCE at module level to prevent threading errors.

    Returns:
        AsyncSqliteSaver instance (already initialized, ready to use)

    Example:
        ```python
        # CORRECT: Get singleton checkpointer (no context manager needed)
        checkpointer = await get_checkpointer()
        workflow = FullWorkflow(use_real_agents=True, checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "REQ-20251030-ABC123"}}
        final_state = await workflow.compiled_graph.ainvoke(initial_state, config)

        # MULTIPLE REQUESTS: Same checkpointer instance, different thread_ids
        checkpointer1 = await get_checkpointer()  # Same instance
        checkpointer2 = await get_checkpointer()  # Same instance
        assert checkpointer1 is checkpointer2  # True
        ```

    Why singleton pattern:
        - AsyncSqliteSaver uses aiosqlite.Connection with background thread
        - Python threads can only be started once
        - Entering context manager multiple times = multiple thread start attempts = RuntimeError
        - Singleton = enter context ONCE = single thread = no errors
        - Different thread_ids still provide state isolation per request
    """
    import threading
    import asyncio
    import gc

    global _checkpointer_instance, _checkpointer_context_manager, _checkpointer_creation_loop_id, _checkpointer_mutex

    # Get current event loop information
    try:
        current_loop = asyncio.get_running_loop()
        current_loop_id = id(current_loop)
    except RuntimeError:
        current_loop = asyncio.get_event_loop()
        current_loop_id = id(current_loop)

    # BUG #11 PART 12 FIX: FAST PATH - Check if checkpointer exists and loop matches (NO LOCKING)
    # This optimizes the common case where checkpointer exists and event loop hasn't changed
    if _checkpointer_instance is not None and _checkpointer_creation_loop_id == current_loop_id:
        logger.debug(
            f"[Bug #11 Part 12] Fast path: Reusing checkpointer "
            f"(loop {current_loop_id}, instance {id(_checkpointer_instance)})"
        )
        return _checkpointer_instance

    # BUG #11 PART 12 FIX: SLOW PATH - Checkpointer doesn't exist or loop changed
    # Use threading.Lock() for thread-safe recreation (NOT event-loop-bound)
    with _checkpointer_mutex:
        # Double-check after acquiring lock (another coroutine might have created it)
        if _checkpointer_instance is not None and _checkpointer_creation_loop_id == current_loop_id:
            logger.debug(
                f"[Bug #11 Part 12] Another coroutine created checkpointer while waiting for lock"
            )
            return _checkpointer_instance

        # Determine if this is recreation or initial creation
        is_recreation = _checkpointer_instance is not None

        # Close old checkpointer if it exists (event loop changed)
        if _checkpointer_instance is not None:
            old_loop_id = _checkpointer_creation_loop_id
            old_instance_id = id(_checkpointer_instance)
            old_context_id = id(_checkpointer_context_manager)

            logger.warning(
                f"[Bug #11 Part 12] Event loop changed - recreating checkpointer"
                f"\n  Old loop ID: {old_loop_id}"
                f"\n  New loop ID: {current_loop_id}"
                f"\n  Old instance ID: {old_instance_id}"
            )

            # Close old checkpointer gracefully
            try:
                if _checkpointer_context_manager is not None:
                    await _checkpointer_context_manager.__aexit__(None, None, None)
                    logger.info("[Bug #11 Part 12] Successfully closed old checkpointer")
            except Exception as e:
                logger.error(f"[Bug #11 Part 12] Error closing old checkpointer: {e}")

            # Clear references
            _checkpointer_instance = None
            _checkpointer_context_manager = None
            _checkpointer_creation_loop_id = None

            # CRITICAL: Give AsyncSqliteSaver time to release its internal resources
            # Without this delay, internal Lock objects may still be bound to old loop
            await asyncio.sleep(0.1)

            # Force garbage collection to destroy old Lock objects
            collected = gc.collect()
            logger.info(
                f"[Bug #11 Part 12] Cleanup complete"
                f"\n  Objects collected by GC: {collected}"
                f"\n  Delay: 100ms (allows AsyncSqliteSaver resource release)"
            )

        # Create new checkpointer in current event loop
        checkpoint_db_path = os.getenv("LANGGRAPH_CHECKPOINT_DB", DEFAULT_CHECKPOINT_DB)
        db_path = Path(checkpoint_db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create and enter context manager
        _checkpointer_context_manager = AsyncSqliteSaver.from_conn_string(str(db_path))
        _checkpointer_instance = await _checkpointer_context_manager.__aenter__()
        _checkpointer_creation_loop_id = current_loop_id

        # BUG #11 PART 12 FIX: Force AsyncSqliteSaver to recreate Lock in current event loop
        # AsyncSqliteSaver creates self.lock in __init__, binding it to constructor's loop
        # When we recreate checkpointer in new loop, we must also recreate its Lock
        # This prevents "RuntimeError: Lock bound to different event loop"
        old_lock_id = id(_checkpointer_instance.lock)
        old_loop_id = id(_checkpointer_instance.loop)
        _checkpointer_instance.lock = asyncio.Lock()
        _checkpointer_instance.loop = current_loop

        # Log creation
        creation_type = "RECREATED" if is_recreation else "CREATED"
        current_thread = threading.current_thread()
        logger.info(
            f"[Bug #11 Part 12] {creation_type} checkpointer"
            f"\n  Instance ID: {id(_checkpointer_instance)}"
            f"\n  Database: {db_path}"
            f"\n  Event loop ID: {current_loop_id}"
            f"\n  Thread: {current_thread.name} (ID: {current_thread.ident})"
            f"\n  Type: {type(_checkpointer_instance).__name__}"
            f"\n  Protection: threading.Lock (mutex ID: {id(_checkpointer_mutex)})"
            f"\n  ===== BUG #11 PART 12 FIX ====="
            f"\n  OLD Lock ID: {old_lock_id} (bound to loop {old_loop_id})"
            f"\n  NEW Lock ID: {id(_checkpointer_instance.lock)} (bound to loop {current_loop_id})"
            f"\n  Lock recreated: YES (prevents event loop binding errors)"
        )

    return _checkpointer_instance


async def clear_checkpointer_cache(db_path: str = None):
    """
    Clear singleton checkpointer instance (useful for testing or cleanup).

    This will close the existing checkpointer's background thread and reset the singleton.
    The next call to get_checkpointer() will create a fresh instance.

    BUG #11 PART 11 FIX: Uses threading.Lock for thread-safe cleanup.

    Args:
        db_path: Ignored (kept for API compatibility)

    Example:
        ```python
        # In tests or cleanup
        await clear_checkpointer_cache()
        # Next get_checkpointer() call will create new instance
        ```
    """
    global _checkpointer_instance, _checkpointer_context_manager, _checkpointer_creation_loop_id, _checkpointer_mutex

    with _checkpointer_mutex:
        if _checkpointer_instance is not None and _checkpointer_context_manager is not None:
            try:
                # Exit the context manager to clean up background thread
                await _checkpointer_context_manager.__aexit__(None, None, None)
                logger.info("[Bug #11 Part 11] Closed and cleared singleton checkpointer")
            except Exception as e:
                logger.warning(f"[Bug #11 Part 11] Error closing checkpointer: {e}")
            finally:
                _checkpointer_instance = None
                _checkpointer_context_manager = None
                _checkpointer_creation_loop_id = None
        else:
            logger.debug("[Bug #11 Part 11] No checkpointer instance to clear")


def create_thread_config(request_id: str) -> Dict[str, Any]:
    """
    Create LangGraph config dict for a specific request.

    Thread ID is set to request_id to enable state isolation per request.
    Each research request runs in its own thread with independent checkpoints.

    Args:
        request_id: Research request identifier (e.g., "REQ-20251030-ABC123")

    Returns:
        Config dict suitable for workflow.ainvoke(state, config=...)

    Example:
        ```python
        config = create_thread_config("REQ-12345")
        result = await workflow.run(initial_state, config=config)
        ```
    """
    return {
        "configurable": {
            "thread_id": request_id,
            # Future enhancements:
            # "user_id": researcher_id,
            # "session_id": session_id,
        }
    }


# ============================================================================
# Database Model Conversion (Sprint 3 - EXISTING)
# ============================================================================


class WorkflowPersistence:
    """
    Persistence layer for LangGraph workflow state

    Responsibilities:
    - Convert LangGraph state → Database models
    - Convert Database models → LangGraph state
    - Save workflow checkpoints
    - Resume workflows from database

    This is the bridge between LangGraph's in-memory state
    and the database's persistent storage.
    """

    def __init__(self, database_url: str = None):
        """
        Initialize persistence layer using shared database engine.

        Bug #11 Part 7 fix (Nov 11, 2025): Removed instance-level caching.
        Engine and session factory properties now always delegate to get_engine()
        and get_session_factory(), which provide correct per-event-loop instances.
        This completes the fix for "Future attached to different loop" errors.

        Args:
            database_url: DEPRECATED (kept for API compatibility, but ignored)
                         Engine is now obtained from get_engine() which manages
                         per-event-loop engines automatically.
        """
        logger.info(
            "[WorkflowPersistence] Initialized (no instance caching - always uses current event loop)"
        )

    @property
    def engine(self):
        """
        Get engine for current event loop.

        Delegates to get_engine() which maintains per-event-loop engines in thread-local storage.
        This prevents "Future attached to a different event loop" errors in Streamlit.

        Bug #11 Part 7 fix (Nov 11, 2025): Remove instance-level caching.
        """
        from app.database import get_engine

        return get_engine()

    @property
    def async_session_maker(self):
        """
        Get session factory for current event loop.

        Delegates to get_session_factory() which creates sessionmakers from the current
        event loop's engine. This prevents "Future attached to a different event loop"
        errors in Streamlit.

        Bug #11 Part 7 fix (Nov 11, 2025): Remove instance-level caching.
        """
        from app.database import get_session_factory

        return get_session_factory()

    async def save_workflow_state(
        self, state: FullWorkflowState, session: Optional[AsyncSession] = None
    ) -> None:
        """
        Save workflow state to database

        Args:
            state: LangGraph workflow state
            session: Optional database session (creates new if None)
        """
        request_id = state["request_id"]
        logger.info(f"[WorkflowPersistence] Saving state for {request_id}")

        if session is None:
            async with self.async_session_maker() as session:
                await self._save_state_internal(state, session)
                await session.commit()
        else:
            await self._save_state_internal(state, session)

    async def _save_state_internal(self, state: FullWorkflowState, session: AsyncSession) -> None:
        """Internal method to save state (used with or without transaction)"""
        request_id = state["request_id"]

        # ===== Update or Create ResearchRequest =====
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        if not request:
            # Create new request
            request = ResearchRequest(
                id=request_id,
                created_at=datetime.fromisoformat(state["created_at"]),
                updated_at=datetime.fromisoformat(state["updated_at"]),
                researcher_name=state["researcher_info"].get("name", "Unknown"),
                researcher_email=state["researcher_info"].get("email", "unknown@example.com"),
                researcher_department=state["researcher_info"].get("department"),
                initial_request=state["researcher_request"],
                current_state=state["current_state"],
                error_message=state.get("error"),
            )
            session.add(request)
        else:
            # Update existing request
            request.updated_at = datetime.fromisoformat(state["updated_at"])
            request.current_state = state["current_state"]
            request.error_message = state.get("error")

            # Update final state if terminal
            if state["current_state"] in ["complete", "not_feasible", "qa_failed", "human_review"]:
                request.final_state = state["current_state"]
                request.completed_at = datetime.fromisoformat(state["updated_at"])

        # ===== Update or Create RequirementsData =====
        if state.get("requirements_complete", False):
            requirements = state.get("requirements", {})

            result = await session.execute(
                select(RequirementsData).where(RequirementsData.request_id == request_id)
            )
            req_data = result.scalar_one_or_none()

            if not req_data:
                req_data = RequirementsData(
                    request_id=request_id,
                    study_title=requirements.get("study_title"),
                    principal_investigator=requirements.get("principal_investigator"),
                    irb_number=requirements.get("irb_number"),
                    inclusion_criteria=requirements.get("inclusion_criteria", []),
                    exclusion_criteria=requirements.get("exclusion_criteria", []),
                    data_elements=requirements.get("data_elements", []),
                    delivery_format=requirements.get("delivery_format"),
                    phi_level=requirements.get("phi_level"),
                    completeness_score=state.get("completeness_score", 0.0),
                    is_complete=state.get("requirements_complete", False),
                )
                session.add(req_data)
            else:
                req_data.study_title = requirements.get("study_title")
                req_data.principal_investigator = requirements.get("principal_investigator")
                req_data.irb_number = requirements.get("irb_number")
                req_data.inclusion_criteria = requirements.get("inclusion_criteria", [])
                req_data.exclusion_criteria = requirements.get("exclusion_criteria", [])
                req_data.data_elements = requirements.get("data_elements", [])
                req_data.delivery_format = requirements.get("delivery_format")
                req_data.phi_level = requirements.get("phi_level")
                req_data.completeness_score = state.get("completeness_score", 0.0)
                req_data.is_complete = state.get("requirements_complete", False)

        # ===== Update or Create FeasibilityReport =====
        if state.get("feasible") is not None:
            result = await session.execute(
                select(FeasibilityReport).where(FeasibilityReport.request_id == request_id)
            )
            feas_report = result.scalar_one_or_none()

            if not feas_report:
                feas_report = FeasibilityReport(
                    request_id=request_id,
                    is_feasible=state.get("feasible", False),
                    feasibility_score=state.get("feasibility_score", 0.0),
                    estimated_cohort_size=state.get("estimated_cohort_size"),
                    phenotype_sql=state.get("phenotype_sql"),
                )
                session.add(feas_report)
            else:
                feas_report.is_feasible = state.get("feasible", False)
                feas_report.feasibility_score = state.get("feasibility_score", 0.0)
                feas_report.estimated_cohort_size = state.get("estimated_cohort_size")
                feas_report.phenotype_sql = state.get("phenotype_sql")

        # ===== Update or Create DataDelivery =====
        if state.get("delivered", False):
            result = await session.execute(
                select(DataDelivery).where(DataDelivery.request_id == request_id)
            )
            delivery = result.scalar_one_or_none()

            delivery_info = state.get("delivery_info", {})

            if not delivery:
                delivery = DataDelivery(
                    request_id=request_id,
                    delivered_at=datetime.fromisoformat(
                        delivery_info.get("delivered_at", datetime.now().isoformat())
                    ),
                    delivery_location=delivery_info.get("location"),
                    delivery_format=delivery_info.get("format"),
                    file_size_bytes=0,  # Would be set in production
                    file_count=1,
                    citation=delivery_info.get("documentation", {}).get("citation"),
                )
                session.add(delivery)
            else:
                delivery.delivered_at = datetime.fromisoformat(
                    delivery_info.get("delivered_at", datetime.now().isoformat())
                )
                delivery.delivery_location = delivery_info.get("location")
                delivery.delivery_format = delivery_info.get("format")
                delivery.citation = delivery_info.get("documentation", {}).get("citation")

        logger.info(f"[WorkflowPersistence] Saved state: {request_id} → {state['current_state']}")

    async def load_workflow_state(
        self, request_id: str, session: Optional[AsyncSession] = None
    ) -> Optional[FullWorkflowState]:
        """
        Load workflow state from database

        Args:
            request_id: Request identifier
            session: Optional database session

        Returns:
            LangGraph workflow state or None if not found
        """
        logger.info(f"[WorkflowPersistence] Loading state for {request_id}")

        if session is None:
            async with self.async_session_maker() as session:
                return await self._load_state_internal(request_id, session)
        else:
            return await self._load_state_internal(request_id, session)

    async def _load_state_internal(
        self, request_id: str, session: AsyncSession
    ) -> Optional[FullWorkflowState]:
        """Internal method to load state"""

        # Load ResearchRequest
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        if not request:
            logger.warning(f"[WorkflowPersistence] Request not found: {request_id}")
            return None

        # Load RequirementsData
        result = await session.execute(
            select(RequirementsData).where(RequirementsData.request_id == request_id)
        )
        requirements_data = result.scalar_one_or_none()

        # Load FeasibilityReport
        result = await session.execute(
            select(FeasibilityReport).where(FeasibilityReport.request_id == request_id)
        )
        feasibility_report = result.scalar_one_or_none()

        # Load DataDelivery
        result = await session.execute(
            select(DataDelivery).where(DataDelivery.request_id == request_id)
        )
        delivery = result.scalar_one_or_none()

        # ===== Convert Database Models → LangGraph State =====
        state: FullWorkflowState = {
            # Request metadata
            "request_id": request.id,
            "current_state": request.current_state,
            "created_at": request.created_at.isoformat(),
            "updated_at": request.updated_at.isoformat(),
            # Researcher info
            "researcher_request": request.initial_request,
            "researcher_info": {
                "name": request.researcher_name,
                "email": request.researcher_email,
                "department": request.researcher_department,
            },
            # Requirements phase
            "requirements": {},
            "conversation_history": [],
            "completeness_score": 0.0,
            "requirements_complete": False,
            "requirements_approved": None,
            "requirements_rejection_reason": None,
            # Feasibility phase
            "phenotype_sql": None,
            "feasibility_score": 0.0,
            "estimated_cohort_size": None,
            "feasible": False,
            "phenotype_approved": None,
            "phenotype_rejection_reason": None,
            # Kickoff phase
            "meeting_scheduled": False,
            "meeting_details": None,
            # Extraction phase
            "extraction_approved": None,
            "extraction_rejection_reason": None,
            "extraction_complete": False,
            "extracted_data_summary": None,
            # QA phase
            "overall_status": None,
            "qa_report": None,
            "qa_approved": None,
            "qa_rejection_reason": None,
            # Delivery phase
            "delivered": False,
            "delivery_info": None,
            # Error handling
            "error": request.error_message,
            "escalation_reason": None,
            # Scope change
            "scope_change_requested": False,
            "scope_approved": None,
        }

        # Populate RequirementsData if exists
        if requirements_data:
            state["requirements"] = {
                "study_title": requirements_data.study_title,
                "principal_investigator": requirements_data.principal_investigator,
                "irb_number": requirements_data.irb_number,
                "inclusion_criteria": requirements_data.inclusion_criteria or [],
                "exclusion_criteria": requirements_data.exclusion_criteria or [],
                "data_elements": requirements_data.data_elements or [],
                "delivery_format": requirements_data.delivery_format,
                "phi_level": requirements_data.phi_level,
            }
            state["completeness_score"] = requirements_data.completeness_score or 0.0
            state["requirements_complete"] = requirements_data.is_complete or False

        # Populate FeasibilityReport if exists
        if feasibility_report:
            state["feasible"] = feasibility_report.is_feasible
            state["feasibility_score"] = feasibility_report.feasibility_score
            state["estimated_cohort_size"] = feasibility_report.estimated_cohort_size
            state["phenotype_sql"] = feasibility_report.phenotype_sql

        # Populate DataDelivery if exists
        if delivery:
            state["delivered"] = True
            state["delivery_info"] = {
                "delivery_id": f"DEL-{request_id}",
                "location": delivery.delivery_location,
                "format": delivery.delivery_format,
                "delivered_at": (
                    delivery.delivered_at.isoformat() if delivery.delivered_at else None
                ),
                "documentation": {"citation": delivery.citation},
            }

        logger.info(
            f"[WorkflowPersistence] Loaded state: {request_id} (state: {state['current_state']})"
        )

        return state

    async def create_initial_state(
        self, request_id: str, researcher_request: str, researcher_info: Dict[str, Any]
    ) -> FullWorkflowState:
        """
        Create initial workflow state for a new request

        Args:
            request_id: Unique request ID
            researcher_request: Natural language request
            researcher_info: Researcher metadata (name, email, department)

        Returns:
            Initial LangGraph workflow state
        """
        logger.info(f"[WorkflowPersistence] Creating initial state for {request_id}")

        now = datetime.now().isoformat()

        state: FullWorkflowState = {
            # Request metadata
            "request_id": request_id,
            "current_state": "new_request",
            "created_at": now,
            "updated_at": now,
            # Researcher info
            "researcher_request": researcher_request,
            "researcher_info": researcher_info,
            # Requirements phase
            "requirements": {},
            "conversation_history": [],
            "completeness_score": 0.0,
            "requirements_complete": False,
            "requirements_approved": None,
            "requirements_rejection_reason": None,
            # Feasibility phase
            "phenotype_sql": None,
            "feasibility_score": 0.0,
            "estimated_cohort_size": None,
            "feasible": False,
            "phenotype_approved": None,
            "phenotype_rejection_reason": None,
            # Kickoff phase
            "meeting_scheduled": False,
            "meeting_details": None,
            # Extraction phase
            "extraction_approved": None,
            "extraction_rejection_reason": None,
            "extraction_complete": False,
            "extracted_data_summary": None,
            # QA phase
            "overall_status": None,
            "qa_report": None,
            "qa_approved": None,
            "qa_rejection_reason": None,
            # Delivery phase
            "delivered": False,
            "delivery_info": None,
            # Error handling
            "error": None,
            "escalation_reason": None,
            # Scope change
            "scope_change_requested": False,
            "scope_approved": None,
        }

        # Save to database
        await self.save_workflow_state(state)

        return state

    async def close(self):
        """Close database connections"""
        await self.engine.dispose()
        logger.info("[WorkflowPersistence] Closed database connections")


# ============================================================================
# Comparison Notes (Sprint 3)
# ============================================================================

# PERSISTENCE PATTERN:
# - Custom: Direct database writes in orchestrator (tightly coupled)
# - LangGraph: Separate persistence layer (clean separation of concerns)
# - Verdict: LangGraph approach is cleaner
#
# STATE MANAGEMENT:
# - Custom: Workflow state scattered across multiple tables (error-prone)
# - LangGraph: Single FullWorkflowState TypedDict (type-safe, centralized)
# - Verdict: LangGraph is more maintainable
#
# RESUMPTION:
# - Custom: Manual state reconstruction from database
# - LangGraph: load_workflow_state() returns ready-to-run state
# - Verdict: LangGraph is simpler
#
# CHECKPOINTING:
# - Custom: Checkpoint logic mixed with business logic
# - LangGraph: save_workflow_state() called at key points
# - Verdict: LangGraph is more explicit
#
# DATA INTEGRITY:
# - Custom: Risk of state/database divergence
# - LangGraph: TypedDict ensures consistent state shape
# - Verdict: LangGraph is safer
#
# OVERALL (Sprint 3 Assessment):
# - Separate persistence layer is a major win
# - TypedDict provides type safety for state management
# - Easy to test persistence logic in isolation
# - Recommend keeping this pattern for production
