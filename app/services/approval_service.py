"""
Approval Service for Human-in-Loop Workflow

Manages approval creation, retrieval, and processing for critical decision points.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import logging

from ..database.models import Approval, ResearchRequest, Escalation
from ..orchestrator.workflow_engine import WorkflowEngine

logger = logging.getLogger(__name__)


class ApprovalService:
    """
    Service for managing human approvals in the workflow

    Handles:
    - Creating approval requests
    - Retrieving pending approvals
    - Approving/rejecting/modifying requests
    - Timeout handling and escalation
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.workflow_engine = WorkflowEngine()

    async def create_approval(
        self,
        request_id: str,
        approval_type: str,
        submitted_by: str,
        approval_data: Dict[str, Any]
    ) -> Approval:
        """
        Create a new approval request

        Args:
            request_id: Research request ID
            approval_type: Type of approval (requirements, phenotype_sql, extraction, qa, scope_change)
            submitted_by: Agent ID that submitted for approval
            approval_data: Data to be approved (SQL, requirements, etc.)

        Returns:
            Created Approval object
        """
        # Calculate timeout based on approval type
        timeout_hours = self.workflow_engine.get_approval_timeout_hours(approval_type)
        timeout_at = datetime.now() + timedelta(hours=timeout_hours)

        approval = Approval(
            request_id=request_id,
            approval_type=approval_type,
            submitted_by=submitted_by,
            approval_data=approval_data,
            submitted_at=datetime.now(),
            timeout_at=timeout_at,
            status="pending"
        )

        self.db.add(approval)
        await self.db.commit()
        await self.db.refresh(approval)

        logger.info(
            f"Created {approval_type} approval for request {request_id}, "
            f"timeout at {timeout_at.isoformat()}"
        )

        return approval

    async def get_pending_approvals(
        self,
        user_role: Optional[str] = None,
        approval_type: Optional[str] = None
    ) -> List[Approval]:
        """
        Get pending approvals, optionally filtered by user role or type

        Args:
            user_role: Filter by user role (informatician, admin, etc.)
            approval_type: Filter by approval type

        Returns:
            List of pending Approval objects
        """
        query = select(Approval).where(Approval.status == "pending")

        if approval_type:
            query = query.where(Approval.approval_type == approval_type)

        # Order by submission time (newest first)
        query = query.order_by(Approval.submitted_at.desc())

        result = await self.db.execute(query)
        approvals = result.scalars().all()

        logger.info(f"Retrieved {len(approvals)} pending approvals")
        return approvals

    async def get_approval(self, approval_id: int) -> Optional[Approval]:
        """Get a specific approval by ID"""
        query = select(Approval).where(Approval.id == approval_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def approve(
        self,
        approval_id: int,
        reviewer: str,
        notes: Optional[str] = None,
        modifications: Optional[Dict[str, Any]] = None
    ) -> Approval:
        """
        Approve a pending request

        Args:
            approval_id: Approval ID
            reviewer: User ID or email of reviewer
            notes: Optional review notes
            modifications: Optional modifications to the approved data

        Returns:
            Updated Approval object
        """
        approval = await self.get_approval(approval_id)
        if not approval:
            raise ValueError(f"Approval {approval_id} not found")

        if approval.status != "pending":
            raise ValueError(f"Approval {approval_id} is not pending (status: {approval.status})")

        # Determine status based on modifications
        status = "modified" if modifications else "approved"

        approval.status = status
        approval.reviewed_at = datetime.now()
        approval.reviewed_by = reviewer
        approval.review_notes = notes
        approval.modifications = modifications

        await self.db.commit()
        await self.db.refresh(approval)

        logger.info(
            f"Approved {approval.approval_type} for request {approval.request_id} "
            f"by {reviewer} (status: {status})"
        )

        return approval

    async def reject(
        self,
        approval_id: int,
        reviewer: str,
        reason: str
    ) -> Approval:
        """
        Reject a pending request

        Args:
            approval_id: Approval ID
            reviewer: User ID or email of reviewer
            reason: Rejection reason

        Returns:
            Updated Approval object
        """
        approval = await self.get_approval(approval_id)
        if not approval:
            raise ValueError(f"Approval {approval_id} not found")

        if approval.status != "pending":
            raise ValueError(f"Approval {approval_id} is not pending (status: {approval.status})")

        approval.status = "rejected"
        approval.reviewed_at = datetime.now()
        approval.reviewed_by = reviewer
        approval.review_notes = reason

        await self.db.commit()
        await self.db.refresh(approval)

        logger.info(
            f"Rejected {approval.approval_type} for request {approval.request_id} "
            f"by {reviewer}: {reason}"
        )

        return approval

    async def modify(
        self,
        approval_id: int,
        reviewer: str,
        modifications: Dict[str, Any],
        notes: Optional[str] = None
    ) -> Approval:
        """
        Approve with modifications

        Args:
            approval_id: Approval ID
            reviewer: User ID or email of reviewer
            modifications: Modified data
            notes: Optional modification notes

        Returns:
            Updated Approval object
        """
        return await self.approve(
            approval_id=approval_id,
            reviewer=reviewer,
            notes=notes,
            modifications=modifications
        )

    async def check_timeouts(self) -> List[Approval]:
        """
        Check for timed out approvals and create escalations

        Returns:
            List of timed out approvals
        """
        now = datetime.now()

        # Find pending approvals that have timed out
        query = select(Approval).where(
            and_(
                Approval.status == "pending",
                Approval.timeout_at < now,
                Approval.timed_out == False
            )
        )

        result = await self.db.execute(query)
        timed_out_approvals = result.scalars().all()

        for approval in timed_out_approvals:
            # Mark as timed out
            approval.timed_out = True
            approval.status = "timeout"

            # Create escalation
            escalation = Escalation(
                request_id=approval.request_id,
                agent="approval_service",
                error=None,
                context={
                    "approval_id": approval.id,
                    "approval_type": approval.approval_type,
                    "submitted_at": approval.submitted_at.isoformat(),
                    "timeout_at": approval.timeout_at.isoformat()
                },
                task={"task": "approve", "approval_type": approval.approval_type},
                escalation_reason="approval_pending",
                severity="high",
                recommended_action=f"Review and approve pending {approval.approval_type} approval",
                status="pending_review"
            )

            self.db.add(escalation)

            # Link escalation to approval
            await self.db.flush()
            approval.escalated = True
            approval.escalation_id = escalation.id

            logger.warning(
                f"Approval {approval.id} timed out for request {approval.request_id}, "
                f"created escalation {escalation.id}"
            )

        await self.db.commit()

        logger.info(f"Checked timeouts: {len(timed_out_approvals)} approvals timed out")
        return timed_out_approvals

    async def get_approval_status(self, request_id: str, approval_type: str) -> Optional[str]:
        """
        Get the status of the most recent approval for a request

        Args:
            request_id: Research request ID
            approval_type: Type of approval

        Returns:
            Approval status or None if not found
        """
        query = select(Approval).where(
            and_(
                Approval.request_id == request_id,
                Approval.approval_type == approval_type
            )
        ).order_by(Approval.submitted_at.desc()).limit(1)

        result = await self.db.execute(query)
        approval = result.scalar_one_or_none()

        return approval.status if approval else None

    async def get_approvals_for_request(self, request_id: str) -> List[Approval]:
        """
        Get all approvals for a research request

        Args:
            request_id: Research request ID

        Returns:
            List of Approval objects
        """
        query = select(Approval).where(
            Approval.request_id == request_id
        ).order_by(Approval.submitted_at)

        result = await self.db.execute(query)
        return result.scalars().all()
