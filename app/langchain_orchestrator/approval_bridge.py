"""
Approval Workflow Bridge for LangGraph Migration (Phase 2.2)

Bridges LangGraph approval state flags with database Approval records.
Maintains audit trail and enables human-in-the-loop approval workflow.

Key responsibilities:
1. Sync LangGraph approval flags → Database Approval table
2. Create Approval records when approvals are requested
3. Query Approval records and update state flags
4. Maintain complete audit trail for compliance

LangGraph State Flags:
- requirements_approved (bool | None)
- phenotype_approved (bool | None)
- extraction_approved (bool | None)
- qa_approved (bool | None)
- scope_approved (bool | None)

Database Approval Types:
- "requirements"
- "phenotype_sql"
- "extraction"
- "qa"
- "scope_change"
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from sqlalchemy.future import select as future_select

from app.database.models import Approval, ResearchRequest

logger = logging.getLogger(__name__)


class ApprovalBridge:
    """
    Bridges LangGraph workflow state with database Approval records.

    Ensures approval decisions are persisted in database for:
    - Audit trail (regulatory compliance)
    - Multi-user access (admin dashboard)
    - Approval timeout tracking
    - Escalation workflow

    Example:
        ```python
        bridge = ApprovalBridge(database_url)

        # After agent requests approval, create DB record
        await bridge.create_approval_request(
            request_id="REQ-123",
            approval_type="phenotype_sql",
            state=workflow_state
        )

        # Check for approval decision (human reviewed in UI)
        updated_state = await bridge.sync_approval_to_state(
            request_id="REQ-123",
            approval_type="phenotype_sql",
            state=workflow_state
        )
        ```
    """

    # Mapping between state flag names and approval types
    STATE_TO_APPROVAL_TYPE = {
        "requirements_approved": "requirements",
        "phenotype_approved": "phenotype_sql",
        "extraction_approved": "extraction",
        "qa_approved": "qa",
        "scope_approved": "scope_change"
    }

    APPROVAL_TYPE_TO_STATE = {
        "requirements": "requirements_approved",
        "phenotype_sql": "phenotype_approved",
        "extraction": "extraction_approved",
        "qa": "qa_approved",
        "scope_change": "scope_approved"
    }

    def __init__(self, database_url: str = "sqlite+aiosqlite:///./dev.db"):
        """
        Initialize approval bridge.

        Args:
            database_url: Async database connection string
        """
        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session_maker = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        logger.info(f"[ApprovalBridge] Initialized with {database_url}")

    async def create_approval_request(
        self,
        request_id: str,
        approval_type: str,
        state: Dict[str, Any],
        submitted_by: str = "langgraph_workflow"
    ) -> Optional[int]:
        """
        Create approval request in database when agent requests human review.

        Args:
            request_id: Research request ID
            approval_type: Type of approval (requirements, phenotype_sql, etc.)
            state: Current LangGraph workflow state
            submitted_by: Agent or system requesting approval

        Returns:
            Approval record ID if created, None if already exists

        Example:
            ```python
            approval_id = await bridge.create_approval_request(
                request_id="REQ-123",
                approval_type="phenotype_sql",
                state=workflow_state
            )
            ```
        """
        async with self.async_session_maker() as session:
            # Check if approval already exists for this type
            result = await session.execute(
                select(Approval).where(
                    Approval.request_id == request_id,
                    Approval.approval_type == approval_type,
                    Approval.status == "pending"
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                logger.info(
                    f"[ApprovalBridge] Approval already exists: {request_id} / {approval_type}"
                )
                return existing.id

            # Extract approval data based on type
            approval_data = self._extract_approval_data(approval_type, state)

            # Create new approval record
            approval = Approval(
                request_id=request_id,
                approval_type=approval_type,
                submitted_at=datetime.now(),
                submitted_by=submitted_by,
                approval_data=approval_data,
                status="pending"
            )

            session.add(approval)
            await session.commit()
            await session.refresh(approval)

            logger.info(
                f"[ApprovalBridge] Created approval request: {request_id} / "
                f"{approval_type} (ID: {approval.id})"
            )

            return approval.id

    async def sync_approval_to_state(
        self,
        request_id: str,
        approval_type: str,
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sync approval decision from database to LangGraph state.

        Queries database for approval status and updates state flags accordingly.

        Args:
            request_id: Research request ID
            approval_type: Type of approval to check
            state: Current LangGraph workflow state

        Returns:
            Updated state dict with approval flags set

        Example:
            ```python
            # Check if human approved phenotype SQL
            updated_state = await bridge.sync_approval_to_state(
                request_id="REQ-123",
                approval_type="phenotype_sql",
                state=current_state
            )
            # updated_state["phenotype_approved"] = True/False/None
            ```
        """
        async with self.async_session_maker() as session:
            # Get latest approval for this type
            result = await session.execute(
                select(Approval)
                .where(
                    Approval.request_id == request_id,
                    Approval.approval_type == approval_type
                )
                .order_by(Approval.created_at.desc())
                .limit(1)
            )
            approval = result.scalar_one_or_none()

            if not approval:
                # No approval record yet, keep state as None
                logger.debug(
                    f"[ApprovalBridge] No approval record found: "
                    f"{request_id} / {approval_type}"
                )
                return state

            # Map approval status to state flag
            state_field = self.APPROVAL_TYPE_TO_STATE.get(approval_type)
            rejection_field = state_field.replace("_approved", "_rejection_reason")

            if approval.status == "approved":
                state[state_field] = True
                state[rejection_field] = None
                logger.info(
                    f"[ApprovalBridge] Synced approval: {request_id} / "
                    f"{approval_type} → APPROVED"
                )

            elif approval.status == "rejected":
                state[state_field] = False
                state[rejection_field] = approval.review_notes or "Rejected by reviewer"
                logger.info(
                    f"[ApprovalBridge] Synced approval: {request_id} / "
                    f"{approval_type} → REJECTED"
                )

            elif approval.status == "modified":
                state[state_field] = True
                state[rejection_field] = None
                # Apply modifications to state if present
                if approval.modifications:
                    state = self._apply_modifications(state, approval_type, approval.modifications)
                logger.info(
                    f"[ApprovalBridge] Synced approval: {request_id} / "
                    f"{approval_type} → APPROVED WITH MODIFICATIONS"
                )

            else:
                # pending, timeout, etc. - keep as None
                state[state_field] = None
                logger.debug(
                    f"[ApprovalBridge] Approval still pending: {request_id} / {approval_type}"
                )

            state["updated_at"] = datetime.now().isoformat()

            return state

    async def sync_all_approvals_to_state(
        self,
        request_id: str,
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Sync ALL approval types for a request.

        Convenience method to check all approval types at once.

        Args:
            request_id: Research request ID
            state: Current workflow state

        Returns:
            State with all approval flags updated
        """
        for approval_type in self.APPROVAL_TYPE_TO_STATE.keys():
            state = await self.sync_approval_to_state(request_id, approval_type, state)

        return state

    async def update_approval_status(
        self,
        approval_id: int,
        status: str,
        reviewed_by: str,
        review_notes: Optional[str] = None,
        modifications: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update approval record with review decision.

        Called by admin dashboard when human reviews approval request.

        Args:
            approval_id: Approval record ID
            status: New status (approved, rejected, modified)
            reviewed_by: User ID or email of reviewer
            review_notes: Optional review comments
            modifications: Optional modifications (for status="modified")

        Returns:
            True if updated successfully

        Example:
            ```python
            # Human reviewer approves in UI
            await bridge.update_approval_status(
                approval_id=123,
                status="approved",
                reviewed_by="admin@example.com",
                review_notes="SQL looks good"
            )
            ```
        """
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(Approval).where(Approval.id == approval_id)
            )
            approval = result.scalar_one_or_none()

            if not approval:
                logger.error(f"[ApprovalBridge] Approval not found: {approval_id}")
                return False

            approval.status = status
            approval.reviewed_at = datetime.now()
            approval.reviewed_by = reviewed_by
            approval.review_notes = review_notes
            approval.modifications = modifications

            await session.commit()

            logger.info(
                f"[ApprovalBridge] Updated approval {approval_id}: "
                f"{approval.approval_type} → {status} (by {reviewed_by})"
            )

            return True

    async def get_pending_approvals(
        self,
        request_id: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        """
        Get all pending approvals, optionally filtered by request.

        Used by admin dashboard to show approval queue.

        Args:
            request_id: Optional filter by specific request

        Returns:
            List of approval dicts with metadata
        """
        async with self.async_session_maker() as session:
            query = select(Approval).where(Approval.status == "pending")

            if request_id:
                query = query.where(Approval.request_id == request_id)

            query = query.order_by(Approval.submitted_at.desc())

            result = await session.execute(query)
            approvals = result.scalars().all()

            return [
                {
                    "id": a.id,
                    "request_id": a.request_id,
                    "approval_type": a.approval_type,
                    "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
                    "submitted_by": a.submitted_by,
                    "approval_data": a.approval_data,
                    "timeout_at": a.timeout_at.isoformat() if a.timeout_at else None
                }
                for a in approvals
            ]

    def _extract_approval_data(
        self,
        approval_type: str,
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract relevant data for approval based on type"""
        if approval_type == "requirements":
            return {
                "requirements": state.get("requirements", {}),
                "completeness_score": state.get("completeness_score", 0.0)
            }

        elif approval_type == "phenotype_sql":
            return {
                "phenotype_sql": state.get("phenotype_sql"),
                "feasibility_score": state.get("feasibility_score", 0.0),
                "estimated_cohort_size": state.get("estimated_cohort_size"),
                "requirements": state.get("requirements", {})
            }

        elif approval_type == "extraction":
            return {
                "phenotype_sql": state.get("phenotype_sql"),
                "estimated_cohort_size": state.get("estimated_cohort_size")
            }

        elif approval_type == "qa":
            return {
                "qa_report": state.get("qa_report", {}),
                "overall_status": state.get("overall_status")
            }

        elif approval_type == "scope_change":
            return {
                "original_requirements": state.get("requirements", {}),
                "requested_changes": state.get("scope_change_reason", "Not specified")
            }

        else:
            return {}

    def _apply_modifications(
        self,
        state: Dict[str, Any],
        approval_type: str,
        modifications: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply reviewer modifications to state"""
        if approval_type == "phenotype_sql" and "phenotype_sql" in modifications:
            state["phenotype_sql"] = modifications["phenotype_sql"]

        elif approval_type == "requirements" and "requirements" in modifications:
            state["requirements"] = modifications["requirements"]

        # Add more modification handlers as needed

        return state

    async def close(self):
        """Close database connections"""
        await self.engine.dispose()
        logger.info("[ApprovalBridge] Closed database connections")


# ============================================================================
# Helper Functions
# ============================================================================

async def create_approval_from_state(
    request_id: str,
    approval_type: str,
    state: Dict[str, Any],
    database_url: str = "sqlite+aiosqlite:///./dev.db"
) -> Optional[int]:
    """
    Convenience function to create approval request.

    Args:
        request_id: Research request ID
        approval_type: Type of approval
        state: Workflow state
        database_url: Database connection string

    Returns:
        Approval ID if created

    Example:
        ```python
        approval_id = await create_approval_from_state(
            "REQ-123",
            "phenotype_sql",
            current_state
        )
        ```
    """
    bridge = ApprovalBridge(database_url)
    approval_id = await bridge.create_approval_request(request_id, approval_type, state)
    await bridge.close()
    return approval_id


async def check_approval_status(
    request_id: str,
    approval_type: str,
    state: Dict[str, Any],
    database_url: str = "sqlite+aiosqlite:///./dev.db"
) -> Dict[str, Any]:
    """
    Convenience function to check and sync approval status.

    Args:
        request_id: Research request ID
        approval_type: Type of approval
        state: Current workflow state
        database_url: Database connection string

    Returns:
        Updated state with approval flag set

    Example:
        ```python
        updated_state = await check_approval_status(
            "REQ-123",
            "phenotype_sql",
            current_state
        )
        # updated_state["phenotype_approved"] = True/False/None
        ```
    """
    bridge = ApprovalBridge(database_url)
    updated_state = await bridge.sync_approval_to_state(request_id, approval_type, state)
    await bridge.close()
    return updated_state


# ============================================================================
# Sprint 6.5 Migration Notes
# ============================================================================

# INTEGRATION WITH LANGGRAPH:
# The approval bridge is called from LangGraph nodes that require human approval:
#
# async def phenotype_review_node(state: FullWorkflowState):
#     """Node that waits for human approval of phenotype SQL"""
#     request_id = state["request_id"]
#
#     # Create approval request if not exists
#     if state.get("phenotype_approved") is None:
#         await create_approval_from_state(
#             request_id,
#             "phenotype_sql",
#             state
#         )
#
#     # Check for approval decision
#     updated_state = await check_approval_status(
#         request_id,
#         "phenotype_sql",
#         state
#     )
#
#     return updated_state
#
# ADMIN DASHBOARD INTEGRATION:
# The admin dashboard uses ApprovalBridge methods:
# - get_pending_approvals() → Show approval queue
# - update_approval_status() → Record approval decision
#
# AUDIT TRAIL:
# All approval decisions are permanently stored in Approval table with:
# - Who approved/rejected (reviewed_by)
# - When (reviewed_at)
# - Why (review_notes)
# - What was approved (approval_data)
