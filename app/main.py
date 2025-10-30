from fastapi import FastAPI
from dotenv import load_dotenv
from contextlib import asynccontextmanager
import logging
import os

# Load environment variables from .env file
load_dotenv()

from .api.health import router as health_router
from .api.text2sql import router as t2s_router
from .api.sql_on_fhir import router as sql_router
from .api.mcp import router as mcp_router
from .api.a2a import router as a2a_router
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
    DeliveryAgent
)
from .agents.coordinator_agent import CoordinatorAgent

logger = logging.getLogger(__name__)

# Global orchestrator instance
orchestrator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup and cleanup on shutdown."""
    global orchestrator

    # Startup
    logger.info("Initializing ResearchFlow application...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

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
    # Cleanup if needed


app = FastAPI(
    title="ResearchFlow - Clinical Research Data Automation",
    description="AI-Powered Multi-Agent System for Clinical Research Data Requests",
    version="2.0.0",
    lifespan=lifespan
)

app.include_router(health_router)
app.include_router(research_router)
app.include_router(t2s_router)
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
        "health": "/health"
    }
