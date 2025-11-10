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

# Global checkpointer singleton (one per database path)
_checkpointer_cache: Dict[str, AsyncSqliteSaver] = {}


async def get_checkpointer() -> AsyncSqliteSaver:
    """
    Get LangGraph checkpointer for state persistence (singleton pattern).

    Creates SQLite database at data/langgraph_checkpoints.db with schema:
    - checkpoints table (thread_id, checkpoint_id, state BLOB)
    - writes table (checkpoint_id, task_id, channel, value)

    This enables:
    - Automatic state snapshots after each node execution
    - Workflow resumption from last checkpoint on failure
    - State isolation per thread_id (request_id)

    Returns:
        AsyncSqliteSaver: Configured checkpointer instance (reused across calls)

    Example:
        ```python
        # Initialize workflow with checkpointing
        checkpointer = await get_checkpointer()
        workflow = FullWorkflow(use_real_agents=True, checkpointer=checkpointer)

        # Run with thread_id for state isolation
        config = {"configurable": {"thread_id": "REQ-20251030-ABC123"}}
        final_state = await workflow.run(initial_state, config=config)

        # After restart/failure, resume from last checkpoint
        resumed_state = await workflow.run({}, config=config)
        ```
    """
    # Read environment variable at runtime (not at module import time)
    checkpoint_db_path = os.getenv("LANGGRAPH_CHECKPOINT_DB", DEFAULT_CHECKPOINT_DB)
    db_path = Path(checkpoint_db_path)
    db_path_str = str(db_path)

    # Return cached checkpointer if exists
    if db_path_str in _checkpointer_cache:
        logger.debug(f"[LangGraph Checkpointer] Reusing existing checkpointer for {db_path}")
        return _checkpointer_cache[db_path_str]

    # Create new checkpointer
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # AsyncSqliteSaver.from_conn_string returns a context manager
    # We need to enter the context and cache the result
    checkpointer_cm = AsyncSqliteSaver.from_conn_string(db_path_str)
    checkpointer = await checkpointer_cm.__aenter__()

    # Cache for reuse
    _checkpointer_cache[db_path_str] = checkpointer

    logger.info(f"[LangGraph Checkpointer] Initialized at {db_path}")
    return checkpointer


def clear_checkpointer_cache(db_path: str = None):
    """
    Clear the checkpointer cache (useful for tests).

    Args:
        db_path: Specific database path to clear, or None to clear all
    """
    global _checkpointer_cache
    if db_path:
        if db_path in _checkpointer_cache:
            del _checkpointer_cache[db_path]
            logger.debug(f"[LangGraph Checkpointer] Cleared cache for {db_path}")
    else:
        _checkpointer_cache.clear()
        logger.debug("[LangGraph Checkpointer] Cleared entire cache")


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

    def __init__(self, database_url: str = "sqlite+aiosqlite:///./dev.db"):
        """
        Initialize persistence layer

        Args:
            database_url: Async database URL
        """
        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session_maker = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        logger.info(f"[WorkflowPersistence] Initialized with {database_url}")

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
