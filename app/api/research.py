"""
Research Request API Endpoints

Provides REST API for submitting and managing research data requests.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from typing import Optional
from datetime import datetime
import logging
import uuid
from pathlib import Path

from ..database import get_db_session, ResearchRequest, DataDelivery
from ..orchestrator.workflow_engine import WorkflowState
from ..services.file_storage import FileStorageService
from ..schemas.research import ResearchRequestSubmission, RequestProcessingTrigger
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research", tags=["research"])

# Global orchestrator reference (set by main.py)
orchestrator = None


def set_orchestrator(orch):
    """Set the orchestrator instance"""
    global orchestrator
    orchestrator = orch


# Schemas migrated to app/schemas/research.py (Sprint 6.1 Phase 2.3 Issue #5)


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
                        "notes": "Request submitted",
                    }
                ],
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
            "next_step": f"Use POST /research/process/{request_id} to begin processing",
        }

    except Exception as e:
        logger.error(f"Error submitting research request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process/{request_id}")
async def process_research_request(
    request_id: str, trigger: Optional[RequestProcessingTrigger] = None
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
            status_code=500, detail="Orchestrator not initialized. Please restart the API server."
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
            "researcher_email": request.researcher_email,
        }

        # Add structured requirements if provided
        if trigger and trigger.structured_requirements:
            context["structured_requirements"] = trigger.structured_requirements
            context["skip_conversation"] = trigger.skip_conversation
            logger.info(
                f"Processing with pre-structured requirements (skip_conversation={trigger.skip_conversation})"
            )

        # Start the orchestrator workflow using route_task
        result = await orchestrator.route_task(
            agent_id="requirements_agent",
            task="gather_requirements",
            context=context,
            from_agent="research_api",
        )

        return {
            "success": True,
            "request_id": request_id,
            "message": "Processing started - agent execution triggered",
            "agent": "requirements_agent",
            "task": "gather_requirements",
            "result": result,
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
                "state_history": request.state_history,
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
                        "created_at": req.created_at.isoformat() if req.created_at else None,
                    }
                    for req in requests
                ],
            }

    except Exception as e:
        logger.error(f"Error listing requests: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Download API Endpoints


@router.get("/{request_id}/delivery")
async def get_delivery_info(request_id: str):
    """
    Get data delivery information for a research request.

    Returns delivery metadata including:
    - Delivery status
    - File list
    - Cohort size
    - QA summary
    - Data dictionary

    Args:
        request_id: Research request ID

    Returns:
        Delivery metadata dictionary
    """
    try:
        async with get_db_session() as session:
            # Get research request
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            request = result.scalar_one_or_none()

            if not request:
                raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

            # Check if request is delivered
            if request.current_state not in [
                WorkflowState.DELIVERED.value,
                WorkflowState.COMPLETE.value,
            ]:
                return {
                    "request_id": request_id,
                    "delivered": False,
                    "current_state": request.current_state,
                    "message": "Data not yet delivered. Current state: " + request.current_state,
                }

            # Get data delivery record
            result = await session.execute(
                select(DataDelivery).where(DataDelivery.request_id == request_id)
            )
            delivery = result.scalar_one_or_none()

            if not delivery:
                raise HTTPException(
                    status_code=404,
                    detail=f"No delivery record found for request {request_id}",
                )

            # Get file list from storage
            storage = FileStorageService()
            files = storage.list_files(request_id)

            return {
                "request_id": request_id,
                "delivered": True,
                "delivery_location": delivery.delivery_location,
                "delivery_format": delivery.delivery_format,
                "cohort_size": delivery.cohort_size,
                "data_elements": delivery.data_elements,
                "files": files,
                "delivered_at": delivery.created_at.isoformat() if delivery.created_at else None,
                "qa_report_summary": (
                    delivery.qa_report.get("summary") if delivery.qa_report else None
                ),
                "notification_sent": delivery.notification_sent,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving delivery info for {request_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{request_id}/download")
async def download_data_package(request_id: str):
    """
    Download complete data package as ZIP file.

    Packages all CSV files, data dictionary, and QA report into a single ZIP.

    Args:
        request_id: Research request ID

    Returns:
        ZIP file as streaming response
    """
    try:
        async with get_db_session() as session:
            # Verify request exists and is delivered
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            request = result.scalar_one_or_none()

            if not request:
                raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

            if request.current_state not in [
                WorkflowState.DELIVERED.value,
                WorkflowState.COMPLETE.value,
            ]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Data not yet delivered. Current state: {request.current_state}",
                )

        # Create ZIP archive
        storage = FileStorageService()
        zip_path = storage.create_download_zip(request_id)

        if not zip_path or not zip_path.exists():
            raise HTTPException(
                status_code=404, detail=f"No data files found for request {request_id}"
            )

        logger.info(f"Streaming data package for request {request_id}")

        # Return ZIP file as streaming response
        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=f"{request_id}_data_package.zip",
            headers={
                "Content-Disposition": f'attachment; filename="{request_id}_data_package.zip"'
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading data package for {request_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{request_id}/download/{filename}")
async def download_specific_file(request_id: str, filename: str):
    """
    Download a specific file from the data package.

    Args:
        request_id: Research request ID
        filename: Name of file to download (e.g., "patient_demographics.csv")

    Returns:
        File as streaming response
    """
    try:
        async with get_db_session() as session:
            # Verify request exists and is delivered
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            request = result.scalar_one_or_none()

            if not request:
                raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

            if request.current_state not in [
                WorkflowState.DELIVERED.value,
                WorkflowState.COMPLETE.value,
            ]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Data not yet delivered. Current state: {request.current_state}",
                )

        # Get file path
        storage = FileStorageService()
        file_path = storage.get_file_path(request_id, filename)

        if not file_path or not file_path.exists():
            raise HTTPException(
                status_code=404, detail=f"File '{filename}' not found for request {request_id}"
            )

        # Determine media type based on file extension
        media_type = "text/csv" if filename.endswith(".csv") else "text/plain"

        logger.info(f"Streaming file {filename} for request {request_id}")

        # Return file as streaming response
        return FileResponse(
            path=str(file_path),
            media_type=media_type,
            filename=filename,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading file {filename} for {request_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
