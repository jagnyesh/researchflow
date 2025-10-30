"""
Materialized Views Management API

Endpoints for creating, refreshing, and monitoring materialized views
in the 'sqlonfhir' schema.

Provides:
- View listing with status and metadata
- Manual refresh triggers
- Health monitoring
- Staleness checking
- Batch operations
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, List, Any, Optional
import logging
import os
import subprocess
import asyncio

from ..services.materialized_view_service import MaterializedViewService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics/materialized-views", tags=["materialized-views"])


# Pydantic models for request/response

class ViewRefreshResponse(BaseModel):
    """Response from view refresh operation"""
    view_name: str
    success: bool
    refresh_duration_ms: Optional[float] = None
    row_count: Optional[int] = None
    error: Optional[str] = None


class ViewStatusResponse(BaseModel):
    """Status information for a materialized view"""
    view_name: str
    exists: bool
    status: str
    row_count: Optional[int] = None
    size: Optional[str] = None
    size_bytes: Optional[int] = None
    last_refreshed_at: Optional[str] = None
    is_stale: bool
    staleness_hours: Optional[float] = None
    needs_refresh: bool


class ViewListResponse(BaseModel):
    """List of materialized views"""
    views: List[Dict[str, Any]]
    total_count: int


class RefreshAllResponse(BaseModel):
    """Response from refresh all operation"""
    total_views: int
    success: int
    failed: int
    results: List[ViewRefreshResponse]


# Helper function to get service instance

async def get_service() -> MaterializedViewService:
    """
    Create MaterializedViewService instance

    Returns:
        MaterializedViewService
    """
    database_url = os.getenv('DATABASE_URL', 'sqlite+aiosqlite:///./dev.db')
    return await MaterializedViewService.create(database_url)


# API Endpoints

@router.get("/", response_model=ViewListResponse)
async def list_materialized_views():
    """
    List all materialized views with metadata

    Returns:
        List of views with status, size, row count, etc.

    Example:
        GET /analytics/materialized-views/
    """
    try:
        service = await get_service()
        try:
            views = await service.list_views()

            logger.info(f"Listed {len(views)} materialized views")

            return ViewListResponse(
                views=views,
                total_count=len(views)
            )

        finally:
            await service.close()

    except Exception as e:
        logger.error(f"Failed to list views: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{view_name}/status", response_model=ViewStatusResponse)
async def get_view_status(view_name: str):
    """
    Get detailed status for a specific materialized view

    Args:
        view_name: Name of the view

    Returns:
        Detailed status including staleness, size, refresh history

    Example:
        GET /analytics/materialized-views/patient_demographics/status
    """
    try:
        service = await get_service()
        try:
            status = await service.get_view_status(view_name)

            if not status.get('exists'):
                raise HTTPException(
                    status_code=404,
                    detail=f"Materialized view '{view_name}' not found"
                )

            return ViewStatusResponse(**status)

        finally:
            await service.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get status for view '{view_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{view_name}/refresh", response_model=ViewRefreshResponse)
async def refresh_view(view_name: str):
    """
    Refresh a specific materialized view

    This re-computes the view with latest data from HAPI database.

    Args:
        view_name: Name of the view to refresh

    Returns:
        Refresh result with timing and row count

    Example:
        POST /analytics/materialized-views/patient_demographics/refresh
    """
    try:
        service = await get_service()
        try:
            logger.info(f"Refreshing view '{view_name}' via API")

            result = await service.refresh_view(view_name)

            return ViewRefreshResponse(**result)

        finally:
            await service.close()

    except Exception as e:
        logger.error(f"Failed to refresh view '{view_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh-all", response_model=RefreshAllResponse)
async def refresh_all_views(background_tasks: BackgroundTasks):
    """
    Refresh all materialized views

    This can be a long-running operation for large datasets.
    Consider using background_tasks for async execution.

    Returns:
        Summary of refresh operations for all views

    Example:
        POST /analytics/materialized-views/refresh-all
    """
    try:
        service = await get_service()
        try:
            logger.info("Refreshing all materialized views via API")

            result = await service.refresh_all_views()

            return RefreshAllResponse(
                total_views=result['total_views'],
                success=result['success'],
                failed=result['failed'],
                results=[ViewRefreshResponse(**r) for r in result['results']]
            )

        finally:
            await service.close()

    except Exception as e:
        logger.error(f"Failed to refresh all views: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh-stale")
async def refresh_stale_views():
    """
    Check for stale views and refresh them

    Only refreshes views that are configured for auto-refresh
    and have exceeded their staleness threshold.

    Returns:
        Summary of refresh operations for stale views

    Example:
        POST /analytics/materialized-views/refresh-stale
    """
    try:
        service = await get_service()
        try:
            logger.info("Checking for stale views via API")

            result = await service.check_and_refresh_stale_views()

            return {
                "total_checked": result['total_checked'],
                "stale_views_found": result['stale_views'],
                "refreshed": result['refreshed'],
                "failed": result.get('failed', 0),
                "results": result['results']
            }

        finally:
            await service.close()

    except Exception as e:
        logger.error(f"Failed to refresh stale views: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-all")
async def create_all_views():
    """
    Create all materialized views from ViewDefinitions

    This runs the scripts/create_materialized_views.py script
    to create all views in the 'sqlonfhir' schema.

    WARNING: This will drop and recreate existing views.

    Returns:
        Script execution result

    Example:
        POST /analytics/materialized-views/create-all
    """
    try:
        logger.info("Creating all materialized views via API")

        # Get HAPI DB URL from environment
        hapi_db_url = os.getenv('HAPI_DB_URL', 'postgresql://hapi:hapi@localhost:5433/hapi')

        # Run the script
        script_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..",
            "scripts",
            "create_materialized_views.py"
        )

        process = await asyncio.create_subprocess_exec(
            "python",
            script_path,
            env={**os.environ, "HAPI_DB_URL": hapi_db_url},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            logger.info("Successfully created all materialized views")
            return {
                "success": True,
                "message": "All materialized views created successfully",
                "output": stdout.decode() if stdout else ""
            }
        else:
            error_msg = stderr.decode() if stderr else "Script execution failed"
            logger.error(f"Failed to create views: {error_msg}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create views: {error_msg}"
            )

    except Exception as e:
        logger.error(f"Error creating views: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{view_name}")
async def drop_view(view_name: str):
    """
    Drop a materialized view

    WARNING: This permanently deletes the view and its data.

    Args:
        view_name: Name of the view to drop

    Returns:
        Success confirmation

    Example:
        DELETE /analytics/materialized-views/patient_demographics
    """
    try:
        service = await get_service()
        try:
            logger.info(f"Dropping view '{view_name}' via API")

            # Execute DROP MATERIALIZED VIEW
            drop_sql = f"DROP MATERIALIZED VIEW IF EXISTS sqlonfhir.{view_name} CASCADE"
            await service.db_client.execute_query(drop_sql)

            # Delete metadata
            from sqlalchemy import delete
            from app.database.models import MaterializedViewMetadata

            stmt = delete(MaterializedViewMetadata).where(
                MaterializedViewMetadata.view_name == view_name
            )
            await service.session.execute(stmt)
            await service.session.commit()

            logger.info(f"✓ Dropped view '{view_name}'")

            return {
                "success": True,
                "message": f"View '{view_name}' dropped successfully"
            }

        finally:
            await service.close()

    except Exception as e:
        logger.error(f"Failed to drop view '{view_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """
    Health check for materialized views system

    Returns:
        Overall health status with view counts

    Example:
        GET /analytics/materialized-views/health
    """
    try:
        service = await get_service()
        try:
            views = await service.list_views()

            stale_count = sum(1 for v in views if v.get('is_stale', False))
            healthy_count = len(views) - stale_count

            return {
                "status": "healthy" if stale_count == 0 else "degraded",
                "total_views": len(views),
                "healthy_views": healthy_count,
                "stale_views": stale_count,
                "schema": "sqlonfhir"
            }

        finally:
            await service.close()

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }
