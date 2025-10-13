"""
Research Request API Endpoints

Provides REST API for submitting and managing research data requests.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import logging
import uuid

from ..database import get_db_session, ResearchRequest
from ..orchestrator.workflow_engine import WorkflowState
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research", tags=["research"])

# Global orchestrator reference (set by main.py)
orchestrator = None


def set_orchestrator(orch):
    """Set the orchestrator instance"""
    global orchestrator
    orchestrator = orch


class ResearchRequestSubmission(BaseModel):
    """Research request submission model"""
    researcher_name: str = Field(..., description="Name of the researcher")
    researcher_email: str = Field(..., description="Email of the researcher")
    researcher_department: Optional[str] = Field(None, description="Department")
    irb_number: str = Field(..., description="IRB approval number")
    initial_request: str = Field(..., description="Natural language research request")
    structured_requirements: Optional[Dict[str, Any]] = Field(None, description="Pre-structured requirements (optional)")


class RequestProcessingTrigger(BaseModel):
    """Trigger for processing a specific request"""
    structured_requirements: Optional[Dict[str, Any]] = Field(None, description="Pre-structured requirements")
    skip_conversation: bool = Field(False, description="Skip conversational requirements gathering")


@router.post("/submit")
async def submit_research_request(submission: ResearchRequestSubmission):
    """
    Submit a new research data request.

    Creates the request and triggers the orchestrator to begin processing.
    """
    try:
        # Generate request ID
        date_str = datetime.now().strftime("%Y%m%d")
        unique_id = str(uuid.uuid4())[:8].upper()
        request_id = f"REQ-{date_str}-{unique_id}"

        # Create research request in database
        async with get_db_session() as session:
            research_request = ResearchRequest(
                id=request_id,
                researcher_name=submission.researcher_name,
                researcher_email=submission.researcher_email,
                researcher_department=submission.researcher_department,
                irb_number=submission.irb_number,
                initial_request=submission.initial_request,
                current_state=WorkflowState.NEW_REQUEST.value,
                current_agent="requirements_agent",
                agents_involved=[],
                state_history=[
                    {
                        "state": WorkflowState.NEW_REQUEST.value,
                        "timestamp": datetime.now().isoformat(),
                        "notes": "Request submitted"
                    }
                ]
            )

            session.add(research_request)
            await session.commit()
            await session.refresh(research_request)

            logger.info(f"Created research request: {request_id}")

        # Trigger orchestrator to process the request
        if orchestrator:
            logger.info(f"Triggering orchestrator for request: {request_id}")
            # Start processing in background
            # Note: In production, this should be a background task
            # For now, we'll return and let the user manually trigger processing
        else:
            logger.warning("Orchestrator not available - request created but not processing")

        return {
            "success": True,
            "request_id": request_id,
            "message": "Research request submitted successfully",
            "status": WorkflowState.NEW_REQUEST.value,
            "next_step": f"Use POST /research/process/{request_id} to begin processing"
        }

    except Exception as e:
        logger.error(f"Error submitting research request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process/{request_id}")
async def process_research_request(
    request_id: str,
    trigger: Optional[RequestProcessingTrigger] = None
):
    """
    Trigger processing of a research request.

    Starts the orchestrator workflow for the specified request.

    Args:
        request_id: Research request ID
        trigger: Optional trigger with structured requirements and skip_conversation flag
    """
    if not orchestrator:
        raise HTTPException(
            status_code=500,
            detail="Orchestrator not initialized. Please restart the API server."
        )

    try:
        # Get the research request
        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            request = result.scalar_one_or_none()

            if not request:
                raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

        logger.info(f"Starting processing for request: {request_id}")

        # Build context for requirements agent
        context = {
            "request_id": request_id,
            "initial_request": request.initial_request,
            "researcher_email": request.researcher_email
        }

        # Add structured requirements if provided
        if trigger and trigger.structured_requirements:
            context["structured_requirements"] = trigger.structured_requirements
            context["skip_conversation"] = trigger.skip_conversation
            logger.info(f"Processing with pre-structured requirements (skip_conversation={trigger.skip_conversation})")

        # Start the orchestrator workflow using route_task
        result = await orchestrator.route_task(
            agent_id="requirements_agent",
            task="gather_requirements",
            context=context,
            from_agent="research_api"
        )

        return {
            "success": True,
            "request_id": request_id,
            "message": "Processing started - agent execution triggered",
            "agent": "requirements_agent",
            "task": "gather_requirements",
            "result": result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing request {request_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{request_id}")
async def get_request_status(request_id: str):
    """
    Get the status of a research request.
    """
    try:
        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            request = result.scalar_one_or_none()

            if not request:
                raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

            return {
                "request_id": request.id,
                "researcher_name": request.researcher_name,
                "researcher_email": request.researcher_email,
                "irb_number": request.irb_number,
                "current_state": request.current_state,
                "current_agent": request.current_agent,
                "created_at": request.created_at.isoformat() if request.created_at else None,
                "updated_at": request.updated_at.isoformat() if request.updated_at else None,
                "agents_involved": request.agents_involved,
                "state_history": request.state_history
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving request {request_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def list_active_requests():
    """
    List all active research requests.
    """
    try:
        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest).order_by(ResearchRequest.created_at.desc()).limit(50)
            )
            requests = result.scalars().all()

            return {
                "count": len(requests),
                "requests": [
                    {
                        "request_id": req.id,
                        "researcher_name": req.researcher_name,
                        "current_state": req.current_state,
                        "current_agent": req.current_agent,
                        "created_at": req.created_at.isoformat() if req.created_at else None
                    }
                    for req in requests
                ]
            }

    except Exception as e:
        logger.error(f"Error listing requests: {e}")
        raise HTTPException(status_code=500, detail=str(e))
