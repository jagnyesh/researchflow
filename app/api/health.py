"""
Health check endpoints for monitoring and status verification
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import Dict, Any, Optional
import logging
import os
import time
from sqlalchemy import select, func

from app.database import get_db_session, ResearchRequest
from app.schemas._errors import log_internal_error
from app.clients.fhir_client import FHIRClient
from app.security import audit_middleware as audit_mw
from app.security.audit_drain import (
    AUDIT_QUEUE_KEY,
    AUDIT_PROCESSING_KEY,
    get_drain_state,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Configuration
FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "http://localhost:8081/fhir")

# Each store probe gives up quickly: /health is polled, and a hung store
# should read as unhealthy, not stall the probe.
STORE_PROBE_TIMEOUT_S = 2.0


async def _probe_hapi_database() -> None:
    import asyncpg

    from app.clients.hapi_db_client import HAPIDBClient

    # Same URL resolution as the runtime client (env default, dialect stripped).
    url = HAPIDBClient().connection_url
    conn = await asyncpg.connect(url, timeout=STORE_PROBE_TIMEOUT_S)
    try:
        await conn.fetchval("SELECT 1", timeout=STORE_PROBE_TIMEOUT_S)
    finally:
        await conn.close()


async def _probe_redis(url: str) -> None:
    import redis.asyncio as redis_async

    client = redis_async.from_url(
        url, socket_connect_timeout=STORE_PROBE_TIMEOUT_S, socket_timeout=STORE_PROBE_TIMEOUT_S
    )
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _probe_audit_redis() -> None:
    # The live client when the lifespan configured one; else the configured URL.
    if audit_mw._audit_redis is not None:
        await audit_mw._audit_redis.ping()
        return
    url = os.getenv("REDIS_AUDIT_URL")
    if not url:
        raise RuntimeError("audit redis not configured")
    await _probe_redis(url)


# Sprint 6.1 Phase 2.2 Issue #3 — audit pipeline thresholds
AUDIT_QUEUE_DEPTH_503_THRESHOLD = int(os.getenv("AUDIT_QUEUE_DEPTH_503_THRESHOLD", "10000"))
AUDIT_DRAIN_STALENESS_503_SECONDS = int(os.getenv("AUDIT_DRAIN_STALENESS_503_SECONDS", "30"))


async def audit_health_check(
    queue_depth_threshold: Optional[int] = None,
    staleness_threshold_sec: Optional[int] = None,
) -> Dict[str, Any]:
    """Snapshot of audit pipeline liveness for /health/ready.

    Returns a dict including a `healthy` boolean. Unhealthy iff:
    - audit Redis client is None or PING fails, OR
    - queue depth exceeds threshold (default 10000), OR
    - last successful drain was more than threshold seconds ago (default 30).
    """
    queue_depth_threshold = queue_depth_threshold or AUDIT_QUEUE_DEPTH_503_THRESHOLD
    staleness_threshold_sec = staleness_threshold_sec or AUDIT_DRAIN_STALENESS_503_SECONDS

    state = get_drain_state()
    last_success = state.get("last_success_monotonic")
    drain_age = time.monotonic() - last_success if last_success is not None else None

    client = audit_mw._audit_redis
    if client is None:
        return {
            "audit_redis": "unreachable",
            "audit_queue_depth": None,
            "audit_processing_depth": None,
            "drain_last_success_seconds_ago": drain_age,
            "drain_restart_count": state.get("restart_count", 0),
            "healthy": False,
        }

    try:
        queue_depth = await client.llen(AUDIT_QUEUE_KEY)
        processing_depth = await client.llen(AUDIT_PROCESSING_KEY)
        redis_status = "ok"
    except Exception:
        return {
            "audit_redis": "unreachable",
            "audit_queue_depth": None,
            "audit_processing_depth": None,
            "drain_last_success_seconds_ago": drain_age,
            "drain_restart_count": state.get("restart_count", 0),
            "healthy": False,
        }

    healthy = True
    if queue_depth > queue_depth_threshold:
        healthy = False
    if drain_age is not None and drain_age > staleness_threshold_sec:
        healthy = False

    return {
        "audit_redis": redis_status,
        "audit_queue_depth": queue_depth,
        "audit_processing_depth": processing_depth,
        "drain_last_success_seconds_ago": drain_age,
        "drain_restart_count": state.get("restart_count", 0),
        "healthy": healthy,
    }


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
    health_status = {"status": "healthy", "timestamp": datetime.now().isoformat(), "components": {}}

    overall_healthy = True

    # Check database connectivity
    try:
        async with get_db_session() as session:
            # Touch the table the app depends on; the count itself is not
            # returned — /health is public, and volume is intel (#179).
            await session.execute(select(func.count(ResearchRequest.id)))
            health_status["components"]["database"] = {"status": "healthy"}
    except Exception as e:
        ref = log_internal_error(logger, "Database health check failed", e)
        health_status["components"]["database"] = {
            "status": "unhealthy",
            "error": f"check failed (ref: {ref})",
        }
        overall_healthy = False

    # Check FHIR server connectivity
    try:
        fhir_client = FHIRClient(base_url=FHIR_BASE_URL)

        # Try a simple metadata query
        await fhir_client.get_metadata()

        health_status["components"]["fhir_server"] = {"status": "healthy"}

        await fhir_client.close()
    except Exception as e:
        ref = log_internal_error(logger, "FHIR server health check failed", e)
        health_status["components"]["fhir_server"] = {
            "status": "unhealthy",
            "error": f"check failed (ref: {ref})",
        }
        overall_healthy = False

    # Data stores the app reads (#274). Status only, never the URL (#179).
    # HAPI Postgres backs every batch/serving/exploratory read, and PHI routes
    # fail closed without the audit Redis, so both count toward overall health.
    # The speed layer is optional (reads fall back to batch), so it doesn't.
    stores = [
        ("hapi_database", _probe_hapi_database, True),
        ("audit_redis", _probe_audit_redis, True),
        (
            "speed_layer_redis",
            lambda: _probe_redis(os.getenv("REDIS_URL", "redis://localhost:6379/0")),
            False,
        ),
    ]
    for name, probe, required in stores:
        try:
            await probe()
            health_status["components"][name] = {"status": "healthy"}
        except Exception as e:
            ref = log_internal_error(
                logger, f"{name} health check failed", e, level=logging.WARNING
            )
            health_status["components"][name] = {
                "status": "unhealthy",
                "error": f"check failed (ref: {ref})",
            }
            if required:
                overall_healthy = False

    # Check cache statistics (if InMemoryRunner is available)
    try:
        # Import here to avoid circular dependencies
        from app.sql_on_fhir.runner.in_memory_runner import InMemoryRunner

        # Create temporary runner to get cache stats
        # Note: This creates a new instance, so stats won't be accurate
        # In production, you'd want to inject a shared runner instance
        temp_runner = InMemoryRunner(
            fhir_client=FHIRClient(base_url=FHIR_BASE_URL), enable_cache=True
        )
        temp_runner.get_cache_stats()
        health_status["components"]["cache"] = {"status": "healthy"}

        await temp_runner.fhir_client.close()
    except Exception as e:
        # WARNING, not ERROR: an unavailable cache is expected and /health is polled.
        log_internal_error(logger, "Cache health check failed", e, level=logging.WARNING)
        health_status["components"]["cache"] = {"status": "unavailable"}

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
    return {"status": "alive", "timestamp": datetime.now().isoformat()}


@router.get("/health/ready")
async def readiness():
    """Public readiness probe — boolean only.

    Two-tier (Sprint 6.1 Phase 2.2 Issue #2 / Finding 2 fix): this endpoint is
    on the public NO_AUDIT_ALLOWLIST so load balancers can poll it without auth.
    Internal state (queue depths, drain restart count) is auth-gated at
    `/health/ready/detailed` to avoid leaking pipeline-failure intel to attackers.
    """
    ready = True
    try:
        async with get_db_session() as session:
            await session.execute(select(1))
    except Exception:
        ready = False

    audit = await audit_health_check()
    if not audit["healthy"]:
        ready = False

    body = {
        "status": "ready" if ready else "not ready",
        "timestamp": datetime.now().isoformat(),
    }
    if not ready:
        return JSONResponse(body, status_code=503)
    return body


@router.get("/health/ready/detailed")
async def readiness_detailed():
    """Auth-gated detailed readiness — full audit pipeline state for operators.

    Default-deny middleware classifies this as a PHI route, so unauthenticated
    callers get 401 + UNAUTH_PHI_ATTEMPT. Authorized operators see component
    health and audit pipeline metrics.
    """
    ready = True
    components = {}

    try:
        async with get_db_session() as session:
            await session.execute(select(1))
            components["database"] = "ready"
    except Exception as e:
        ref = log_internal_error(logger, "Readiness database check failed", e)
        components["database"] = f"not ready (ref: {ref})"
        ready = False

    audit = await audit_health_check()
    if not audit["healthy"]:
        ready = False

    body = {
        "status": "ready" if ready else "not ready",
        "timestamp": datetime.now().isoformat(),
        "components": components,
        **{k: v for k, v in audit.items() if k != "healthy"},
    }
    if not ready:
        return JSONResponse(body, status_code=503)
    return body
