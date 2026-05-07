from fastapi import FastAPI
from dotenv import load_dotenv
from contextlib import asynccontextmanager
import asyncio
import logging
import os

import redis.asyncio as redis_async

# Load environment variables from .env file
load_dotenv()

from .api.health import router as health_router
from .api.sql_on_fhir import router as sql_router
from .api.mcp import router as mcp_router
from .api.a2a import router as a2a_router
from .api.auth import router as auth_router
from .api.users import router as users_router
from .api.analytics import router as analytics_router
from .api.materialized_views import router as materialized_views_router
from .api.approvals import router as approvals_router, set_orchestrator as set_approvals_orch
from .api.research import router as research_router, set_orchestrator as set_research_orch
from .orchestrator.orchestrator import ResearchRequestOrchestrator
from .database import init_db
from .agents import (
    RequirementsAgent,
    PhenotypeValidationAgent,
    CalendarAgent,
    DataExtractionAgent,
    QualityAssuranceAgent,
    DeliveryAgent,
)
from .agents.coordinator_agent import CoordinatorAgent
from .security.rate_limit import setup_rate_limiting
from .security import audit_middleware as audit_mw
from .security.audit_drain import audit_drain_loop, recovery_sweep
from .security.body_size import body_size_limit_middleware
from .security.tls import (
    install_tls_middleware_if_production,
    maybe_warn_about_forwarded_allow_ips,
)
from .schemas import phi_safe_validation_handler
from fastapi.exceptions import RequestValidationError

logger = logging.getLogger(__name__)

# Global orchestrator instance
orchestrator = None

# Audit pipeline state (Sprint 6.1 Phase 2.2 Issue #1)
_audit_drain_task = None
_audit_drain_stop = None
_audit_redis_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup and cleanup on shutdown."""
    global orchestrator, _audit_drain_task, _audit_drain_stop, _audit_redis_client

    # Startup
    logger.info("Initializing ResearchFlow application...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Phase 3a: warn if production with default-permissive forwarded-allow-ips
    maybe_warn_about_forwarded_allow_ips()

    # Initialize audit pipeline (Sprint 6.1 Phase 2.2)
    audit_redis_url = os.getenv("REDIS_AUDIT_URL")
    if audit_redis_url:
        _audit_redis_client = redis_async.from_url(
            audit_redis_url, encoding="utf-8", decode_responses=True, socket_timeout=5
        )
        audit_mw.set_audit_redis(_audit_redis_client)
        # Issue #3: recover orphaned audit:processing entries from prior crash
        try:
            recovered = await recovery_sweep(_audit_redis_client)
            if recovered:
                logger.warning(
                    "audit pipeline: recovered %d orphaned entries from prior process",
                    recovered,
                )
        except Exception:
            logger.exception("audit recovery sweep failed; continuing")
        _audit_drain_stop = asyncio.Event()
        _audit_drain_task = asyncio.create_task(
            audit_drain_loop(_audit_redis_client, _audit_drain_stop)
        )
        logger.info(f"Audit pipeline initialized (REDIS_AUDIT_URL={audit_redis_url})")
    else:
        logger.warning(
            "REDIS_AUDIT_URL not set; audit pipeline disabled (PHI routes will fail-closed)"
        )

    # Check if orchestrator should be enabled (for full workflow automation)
    # Set ENABLE_ORCHESTRATOR=false to run analytics-only mode
    enable_orchestrator = os.getenv("ENABLE_ORCHESTRATOR", "true").lower() == "true"

    if enable_orchestrator:
        logger.info("Initializing orchestrator and agents (full workflow mode)...")

        # Initialize orchestrator
        orchestrator = ResearchRequestOrchestrator()
        logger.info("Orchestrator initialized")

        # Get HAPI FHIR database URL from environment
        hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")
        logger.info(f"Using HAPI database: {hapi_db_url}")

        # Initialize and register all agents
        requirements_agent = RequirementsAgent()
        phenotype_agent = PhenotypeValidationAgent(database_url=hapi_db_url)
        calendar_agent = CalendarAgent()
        extraction_agent = DataExtractionAgent()
        qa_agent = QualityAssuranceAgent()
        delivery_agent = DeliveryAgent()
        coordinator_agent = CoordinatorAgent()

        orchestrator.register_agent("requirements_agent", requirements_agent)
        orchestrator.register_agent("phenotype_agent", phenotype_agent)
        orchestrator.register_agent("calendar_agent", calendar_agent)
        orchestrator.register_agent("extraction_agent", extraction_agent)
        orchestrator.register_agent("qa_agent", qa_agent)
        orchestrator.register_agent("delivery_agent", delivery_agent)
        orchestrator.register_agent("coordinator_agent", coordinator_agent)
        logger.info("All agents registered with orchestrator")

        # Set orchestrator in API routers
        set_approvals_orch(orchestrator)
        set_research_orch(orchestrator)
        logger.info("Orchestrator connected to API endpoints")
    else:
        logger.info("Orchestrator disabled - running in analytics-only mode")
        orchestrator = None

    logger.info("ResearchFlow application ready")

    yield

    # Shutdown
    logger.info("Shutting down ResearchFlow application...")
    if _audit_drain_stop is not None:
        _audit_drain_stop.set()
    if _audit_drain_task is not None:
        try:
            await asyncio.wait_for(_audit_drain_task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _audit_drain_task.cancel()
    if _audit_redis_client is not None:
        await _audit_redis_client.aclose()
    audit_mw.set_audit_redis(None)


app = FastAPI(
    title="ResearchFlow - Clinical Research Data Automation",
    description="AI-Powered Multi-Agent System for Clinical Research Data Requests",
    version="2.0.0",
    lifespan=lifespan,
)

# Setup rate limiting (Sprint 6 Phase 1.4)
setup_rate_limiting(app)

# Audit middleware (Sprint 6.1 Phase 2.2 — default-deny + fail-closed PHI gate)
app.middleware("http")(audit_mw.audit_middleware)

# Body-size limit middleware (Sprint 6.1 Phase 2.3 CSO Finding 1 fix — defense-in-depth
# DoS guard). Added AFTER audit_middleware so it runs FIRST (FastAPI middleware order
# is reverse of registration). 413-rejected requests don't pollute the audit queue.
app.middleware("http")(body_size_limit_middleware)

# TLS enforcement (Sprint 6.1 Phase 3a Issue #7 — production only). Added LAST so it
# runs FIRST in the middleware chain: HTTP redirects don't pollute the audit queue,
# /health* probes pass through, HSTS emitted on HTTPS responses.
install_tls_middleware_if_production(app)

# PHI-safe validation error handler (Sprint 6.1 Phase 2.3 Issue #4 — strips
# input/url/ctx from 422 responses to close the Sentry/Datadog leak vector)
app.add_exception_handler(RequestValidationError, phi_safe_validation_handler)

app.include_router(health_router)
app.include_router(auth_router)  # Authentication endpoints (Sprint 6)
app.include_router(users_router)  # User management endpoints (Sprint 6)
app.include_router(research_router)
app.include_router(sql_router)
app.include_router(mcp_router)
app.include_router(a2a_router)
app.include_router(analytics_router)
app.include_router(materialized_views_router)
app.include_router(approvals_router)


@app.get("/")
async def root():
    """Root endpoint with system information."""
    return {
        "name": "ResearchFlow",
        "version": "2.0.0",
        "status": "operational",
        "orchestrator_initialized": orchestrator is not None,
        "documentation": "/docs",
        "health": "/health",
    }
