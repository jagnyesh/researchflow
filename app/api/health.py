"""
Health check endpoints for monitoring and status verification
"""

from fastapi import APIRouter
from datetime import datetime
from typing import Dict, Any
import logging
import os
from sqlalchemy import select, func

from app.database import get_db_session, ResearchRequest
from app.clients.fhir_client import FHIRClient

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration
FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "http://localhost:8081/fhir")


@router.get("/health")
async def health() -> Dict[str, Any]:
    """
    Comprehensive health check endpoint

    Checks:
    - Overall system status
    - FHIR server connectivity
    - Database connectivity
    - Active request count
    - Cache statistics (if available)

    Returns:
        Health status with component checks
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "components": {}
    }

    overall_healthy = True

    # Check database connectivity
    try:
        async with get_db_session() as session:
            # Simple query to test connection
            result = await session.execute(select(func.count(ResearchRequest.id)))
            total_requests = result.scalar()

            # Count active requests
            active_result = await session.execute(
                select(func.count(ResearchRequest.id)).where(
                    ResearchRequest.completed_at.is_(None)
                )
            )
            active_requests = active_result.scalar()

            health_status["components"]["database"] = {
                "status": "healthy",
                "total_requests": total_requests,
                "active_requests": active_requests
            }
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health_status["components"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        overall_healthy = False

    # Check FHIR server connectivity
    try:
        fhir_client = FHIRClient(base_url=FHIR_BASE_URL)

        # Try a simple metadata query
        metadata = await fhir_client.get_metadata()

        health_status["components"]["fhir_server"] = {
            "status": "healthy",
            "url": FHIR_BASE_URL,
            "version": metadata.get("fhirVersion", "unknown") if metadata else "unknown"
        }

        await fhir_client.close()
    except Exception as e:
        logger.error(f"FHIR server health check failed: {e}")
        health_status["components"]["fhir_server"] = {
            "status": "unhealthy",
            "url": FHIR_BASE_URL,
            "error": str(e)
        }
        overall_healthy = False

    # Check cache statistics (if InMemoryRunner is available)
    try:
        # Import here to avoid circular dependencies
        from app.sql_on_fhir.runner.in_memory_runner import InMemoryRunner

        # Create temporary runner to get cache stats
        # Note: This creates a new instance, so stats won't be accurate
        # In production, you'd want to inject a shared runner instance
        temp_runner = InMemoryRunner(
            fhir_client=FHIRClient(base_url=FHIR_BASE_URL),
            enable_cache=True
        )
        cache_stats = temp_runner.get_cache_stats()

        health_status["components"]["cache"] = {
            "status": "healthy",
            **cache_stats
        }

        await temp_runner.fhir_client.close()
    except Exception as e:
        logger.warning(f"Cache health check failed: {e}")
        health_status["components"]["cache"] = {
            "status": "unavailable",
            "message": "Cache statistics not available"
        }

    # Set overall status
    health_status["status"] = "healthy" if overall_healthy else "unhealthy"

    return health_status


@router.get("/health/live")
async def liveness() -> Dict[str, str]:
    """
    Kubernetes liveness probe endpoint

    Returns basic status to indicate the service is running.
    Does not perform deep health checks.

    Returns:
        Simple status message
    """
    return {
        "status": "alive",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/health/ready")
async def readiness() -> Dict[str, Any]:
    """
    Kubernetes readiness probe endpoint

    Checks if the service is ready to accept traffic.
    Performs quick connectivity checks.

    Returns:
        Readiness status with critical component checks
    """
    ready = True
    components = {}

    # Check database
    try:
        async with get_db_session() as session:
            await session.execute(select(1))
            components["database"] = "ready"
    except Exception as e:
        components["database"] = f"not ready: {str(e)}"
        ready = False

    # Check FHIR server
    try:
        fhir_client = FHIRClient(base_url=FHIR_BASE_URL)
        await fhir_client.get_metadata()
        components["fhir_server"] = "ready"
        await fhir_client.close()
    except Exception as e:
        components["fhir_server"] = f"not ready: {str(e)}"
        ready = False

    return {
        "status": "ready" if ready else "not ready",
        "timestamp": datetime.now().isoformat(),
        "components": components
    }
