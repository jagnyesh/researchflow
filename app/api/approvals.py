"""
Approval API Endpoints

Provides REST API for managing human approvals in the ResearchFlow workflow.
Allows informaticians and admins to review and approve/reject requests.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

from ..database import get_db_session
from ..services.approval_service import ApprovalService
from ..orchestrator.orchestrator import ResearchRequestOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApprovalResponse(BaseModel):
    """Approval decision request"""
    decision: str = Field(..., description="approve, reject, or modify")
    reviewer: str = Field(..., description="User ID or email of reviewer")
    notes: Optional[str] = Field(None, description="Review notes")
    modifications: Optional[Dict[str, Any]] = Field(None, description="Modifications (for modify decision)")


class ScopeChangeRequest(BaseModel):
    """Request to change scope mid-workflow"""
    request_id: str = Field(..., description="Research request ID")
    requested_by: str = Field(..., description="Email of requester")
    requested_changes: Dict[str, Any] = Field(..., description="Requested changes to requirements")
    reason: Optional[str] = Field(None, description="Reason for scope change")


# Global orchestrator instance (will be set by main.py)
orchestrator: Optional[ResearchRequestOrchestrator] = None


def set_orchestrator(orch: ResearchRequestOrchestrator):
    """Set the orchestrator instance"""
    global orchestrator
    orchestrator = orch


@router.get("/pending")
async def get_pending_approvals(
    approval_type: Optional[str] = None,
    user_role: Optional[str] = None
):
    """
    Get all pending approvals

    Args:
        approval_type: Filter by approval type (requirements, phenotype_sql, etc.)
        user_role: Filter by user role (informatician, admin)

    Returns:
        List of pending approvals
    """
    try:
        async with get_db_session() as session:
            approval_service = ApprovalService(session)

            approvals = await approval_service.get_pending_approvals(
                user_role=user_role,
                approval_type=approval_type
            )

            return {
                "count": len(approvals),
                "approvals": [
                    {
                        "id": approval.id,
                        "request_id": approval.request_id,
                        "approval_type": approval.approval_type,
                        "submitted_at": approval.submitted_at.isoformat(),
                        "submitted_by": approval.submitted_by,
                        "timeout_at": approval.timeout_at.isoformat() if approval.timeout_at else None,
                        "approval_data": approval.approval_data
                    }
                    for approval in approvals
                ]
            }

    except Exception as e:
        logger.error(f"Error retrieving pending approvals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{approval_id}")
async def get_approval(approval_id: int):
    """
    Get a specific approval by ID

    Args:
        approval_id: Approval ID

    Returns:
        Approval details
    """
    try:
        async with get_db_session() as session:
            approval_service = ApprovalService(session)
            approval = await approval_service.get_approval(approval_id)

            if not approval:
                raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")

            return {
                "id": approval.id,
                "request_id": approval.request_id,
                "approval_type": approval.approval_type,
                "status": approval.status,
                "submitted_at": approval.submitted_at.isoformat(),
                "submitted_by": approval.submitted_by,
                "approval_data": approval.approval_data,
                "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None,
                "reviewed_by": approval.reviewed_by,
                "review_notes": approval.review_notes,
                "modifications": approval.modifications,
                "timeout_at": approval.timeout_at.isoformat() if approval.timeout_at else None,
                "timed_out": approval.timed_out,
                "escalated": approval.escalated
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving approval {approval_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{approval_id}/respond")
async def respond_to_approval(approval_id: int, response: ApprovalResponse):
    """
    Respond to a pending approval

    Args:
        approval_id: Approval ID
        response: Approval decision (approve/reject/modify)

    Returns:
        Success message and next workflow state
    """
    try:
        # If orchestrator is available, use full workflow integration
        if orchestrator:
            await orchestrator.process_approval_response(
                approval_id=approval_id,
                reviewer=response.reviewer,
                decision=response.decision,
                notes=response.notes,
                modifications=response.modifications
            )
        else:
            # Without orchestrator, just update the approval status
            # This is useful for testing the approval UI
            async with get_db_session() as session:
                approval_service = ApprovalService(session)

                if response.decision == "approve":
                    await approval_service.approve(
                        approval_id,
                        response.reviewer,
                        response.notes,
                        response.modifications
                    )
                elif response.decision == "reject":
                    await approval_service.reject(
                        approval_id,
                        response.reviewer,
                        response.notes or "Rejected"
                    )
                elif response.decision == "modify":
                    await approval_service.modify(
                        approval_id,
                        response.reviewer,
                        response.modifications,
                        response.notes
                    )
                else:
                    raise ValueError(f"Invalid decision: {response.decision}")

                logger.info(
                    f"Approval {approval_id} {response.decision}d by {response.reviewer} "
                    "(without workflow continuation - orchestrator not available)"
                )

        return {
            "success": True,
            "message": f"Approval {approval_id} {response.decision}d by {response.reviewer}",
            "approval_id": approval_id,
            "decision": response.decision
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing approval {approval_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/request/{request_id}")
async def get_approvals_for_request(request_id: str):
    """
    Get all approvals for a research request

    Args:
        request_id: Research request ID

    Returns:
        List of approvals for the request
    """
    try:
        async with get_db_session() as session:
            approval_service = ApprovalService(session)
            approvals = await approval_service.get_approvals_for_request(request_id)

            return {
                "request_id": request_id,
                "count": len(approvals),
                "approvals": [
                    {
                        "id": approval.id,
                        "approval_type": approval.approval_type,
                        "status": approval.status,
                        "submitted_at": approval.submitted_at.isoformat(),
                        "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None,
                        "reviewed_by": approval.reviewed_by,
                        "review_notes": approval.review_notes
                    }
                    for approval in approvals
                ]
            }

    except Exception as e:
        logger.error(f"Error retrieving approvals for request {request_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scope-change")
async def request_scope_change(request: ScopeChangeRequest):
    """
    Request a scope change for an active research request

    This allows researchers to modify their requirements mid-workflow without restarting.
    The coordinator agent will analyze the impact and route for approval.

    Args:
        request: Scope change request details

    Returns:
        Approval ID for the scope change request
    """
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")

    try:
        # Get current request state
        request_status = await orchestrator.get_request_status(request.request_id)

        if not request_status:
            raise HTTPException(status_code=404, detail=f"Request {request.request_id} not found")

        # Check if request is in a state that allows scope changes
        terminal_states = ["complete", "failed", "delivered"]
        if request_status['current_state'] in terminal_states:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot change scope for request in state: {request_status['current_state']}"
            )

        logger.info(
            f"Scope change requested for {request.request_id} by {request.requested_by}"
        )

        # Route to coordinator agent for scope change handling
        coordinator = orchestrator.agents.get('coordinator_agent')
        if not coordinator:
            raise HTTPException(status_code=500, detail="Coordinator agent not available")

        # Execute scope change analysis
        result = await coordinator.handle_task(
            task='handle_scope_change',
            context={
                'request_id': request.request_id,
                'current_state': request_status['current_state'],
                'requested_changes': request.requested_changes,
                'requested_by': request.requested_by,
                'reason': request.reason,
                'original_requirements': {}  # TODO: Get from database
            }
        )

        # Create approval for scope change
        async with get_db_session() as session:
            approval_service = ApprovalService(session)

            approval = await approval_service.create_approval(
                request_id=request.request_id,
                approval_type="scope_change",
                submitted_by=request.requested_by,
                approval_data={
                    "requested_changes": request.requested_changes,
                    "reason": request.reason,
                    "impact_analysis": result.get('impact_analysis', {}),
                    "current_state": request_status['current_state']
                }
            )

            # Send notification to stakeholders
            await coordinator.handle_task(
                task='send_scope_change_notification',
                context={
                    'request_id': request.request_id,
                    'approval_id': approval.id,
                    'requested_by': request.requested_by,
                    'current_state': request_status['current_state'],
                    'requested_changes': request.requested_changes,
                    'impact_analysis': result.get('impact_analysis', {})
                }
            )

            return {
                "success": True,
                "message": "Scope change request submitted for approval",
                "approval_id": approval.id,
                "request_id": request.request_id,
                "impact_analysis": result.get('impact_analysis', {})
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing scope change request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check-timeouts")
async def check_approval_timeouts():
    """
    Check for timed out approvals and create escalations

    This should be called periodically (e.g., every hour) by a scheduler

    Returns:
        List of timed out approvals
    """
    try:
        async with get_db_session() as session:
            approval_service = ApprovalService(session)
            timed_out = await approval_service.check_timeouts()

            return {
                "success": True,
                "timed_out_count": len(timed_out),
                "timed_out_approvals": [
                    {
                        "id": approval.id,
                        "request_id": approval.request_id,
                        "approval_type": approval.approval_type,
                        "timeout_at": approval.timeout_at.isoformat(),
                        "escalation_id": approval.escalation_id
                    }
                    for approval in timed_out
                ]
            }

    except Exception as e:
        logger.error(f"Error checking approval timeouts: {e}")
        raise HTTPException(status_code=500, detail=str(e))
