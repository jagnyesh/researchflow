"""
Research Request API Endpoints

Read-side REST API for research data requests: status, lists and downloads.
Requests are created and started through LangGraphRequestFacade (#273).
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
import logging
from pathlib import Path

from ..database import get_db_session, ResearchRequest, DataDelivery
from ..schemas._errors import internal_error
from ..database.workflow_states import WorkflowState
from ..services.file_storage import FileStorageService
from sqlalchemy import func, select

from ..security.dependencies import User, get_current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research", tags=["research"])

# Default-deny: any other role (researcher or unknown) sees only its own requests.
ALL_REQUESTS_ROLES = {"admin", "data_steward"}


def _visible_requests(user: User):
    """SELECT over the research requests `user` may see."""
    query = select(ResearchRequest)
    if user.role not in ALL_REQUESTS_ROLES:
        query = query.where(func.lower(ResearchRequest.researcher_email) == user.email.lower())
    return query


@router.get("/{request_id}")
async def get_request_status(request_id: str, user: User = Depends(get_current_active_user)):
    """
    Get the status of a research request.
    """
    try:
        async with get_db_session() as session:
            result = await session.execute(
                _visible_requests(user).where(ResearchRequest.id == request_id)
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
        raise internal_error(logger, f"Error retrieving request {request_id}", e)


@router.get("/")
async def list_active_requests(user: User = Depends(get_current_active_user)):
    """
    List all active research requests.
    """
    try:
        async with get_db_session() as session:
            result = await session.execute(
                _visible_requests(user).order_by(ResearchRequest.created_at.desc()).limit(50)
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
        raise internal_error(logger, "Error listing requests", e)


# Download API Endpoints


@router.get("/{request_id}/delivery")
async def get_delivery_info(request_id: str, user: User = Depends(get_current_active_user)):
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
                _visible_requests(user).where(ResearchRequest.id == request_id)
            )
            request = result.scalar_one_or_none()

            if not request:
                raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

            # Check if request is delivered
            # "complete" is LangGraph's only delivered state (#53).
            if request.current_state != WorkflowState.COMPLETE.value:
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
        raise internal_error(logger, f"Error retrieving delivery info for {request_id}", e)


@router.get("/{request_id}/download")
async def download_data_package(request_id: str, user: User = Depends(get_current_active_user)):
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
                _visible_requests(user).where(ResearchRequest.id == request_id)
            )
            request = result.scalar_one_or_none()

            if not request:
                raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

            # "complete" is LangGraph's only delivered state (#53).
            if request.current_state != WorkflowState.COMPLETE.value:
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
        raise internal_error(logger, f"Error downloading data package for {request_id}", e)


@router.get("/{request_id}/download/{filename}")
async def download_specific_file(
    request_id: str, filename: str, user: User = Depends(get_current_active_user)
):
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
                _visible_requests(user).where(ResearchRequest.id == request_id)
            )
            request = result.scalar_one_or_none()

            if not request:
                raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

            # "complete" is LangGraph's only delivered state (#53).
            if request.current_state != WorkflowState.COMPLETE.value:
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
        raise internal_error(logger, f"Error downloading file {filename} for {request_id}", e)
