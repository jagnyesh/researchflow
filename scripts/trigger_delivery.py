#!/usr/bin/env python3
"""
Trigger delivery_agent for stuck request REQ-20251106-D710278F

The database records (requirements_data, feasibility_reports) now exist.
This script just triggers the delivery_agent to complete the workflow.
"""

import asyncio
import sys
import os
from sqlalchemy import select

sys.path.insert(0, "/Users/jagnyesh/Development/FHIR_PROJECT")

from app.database import get_db_session
from app.database.models import ResearchRequest, RequirementsData, FeasibilityReport
from app.orchestrator.orchestrator import ResearchRequestOrchestrator
from app.agents.requirements_agent import RequirementsAgent
from app.agents.phenotype_agent import PhenotypeValidationAgent
from app.agents.calendar_agent import CalendarAgent
from app.agents.extraction_agent import DataExtractionAgent
from app.agents.qa_agent import QualityAssuranceAgent
from app.agents.delivery_agent import DeliveryAgent


async def trigger_delivery(request_id: str):
    """Trigger delivery_agent with proper context"""

    print(f"\n🚀 Triggering delivery_agent for {request_id}...")

    # Initialize orchestrator and register all agents
    orchestrator = ResearchRequestOrchestrator()

    # Get HAPI FHIR database URL from environment
    hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")

    # Convert to asyncpg format
    if "postgresql://" in hapi_db_url and "+asyncpg" not in hapi_db_url:
        hapi_db_url_async = hapi_db_url.replace("postgresql://", "postgresql+asyncpg://")
    else:
        hapi_db_url_async = hapi_db_url

    # Register all agents
    orchestrator.register_agent("requirements_agent", RequirementsAgent())
    orchestrator.register_agent(
        "phenotype_agent", PhenotypeValidationAgent(database_url=hapi_db_url_async)
    )
    orchestrator.register_agent("calendar_agent", CalendarAgent())
    orchestrator.register_agent(
        "extraction_agent", DataExtractionAgent(database_url=hapi_db_url_async)
    )
    orchestrator.register_agent("qa_agent", QualityAssuranceAgent())
    orchestrator.register_agent("delivery_agent", DeliveryAgent())

    print(f"✅ Registered 6 agents")

    # Get the request with all related data
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one()

        result = await session.execute(
            select(RequirementsData).where(RequirementsData.request_id == request_id)
        )
        requirements = result.scalar_one()

        result = await session.execute(
            select(FeasibilityReport).where(FeasibilityReport.request_id == request_id)
        )
        feasibility = result.scalar_one()

    # Build context
    context = {
        "request_id": request_id,
        "structured_requirements": {
            "study_title": requirements.study_title,
            "principal_investigator": requirements.principal_investigator,
            "irb_number": requirements.irb_number,
            "inclusion_criteria": requirements.inclusion_criteria,
            "exclusion_criteria": requirements.exclusion_criteria,
            "data_elements": requirements.data_elements,
            "time_period": {
                "start": (
                    requirements.time_period_start.isoformat()
                    if requirements.time_period_start
                    else None
                ),
                "end": (
                    requirements.time_period_end.isoformat()
                    if requirements.time_period_end
                    else None
                ),
            },
            "phi_level": requirements.phi_level,
            "delivery_format": requirements.delivery_format,
        },
        "phenotype_sql": feasibility.phenotype_sql,
        "estimated_cohort": feasibility.estimated_cohort_size,
        "phi_level": requirements.phi_level,
        "delivery_format": requirements.delivery_format,
    }

    print(f"✅ Built context:")
    print(f"   - Study: {requirements.study_title}")
    print(f"   - PHI level: {requirements.phi_level}")
    print(f"   - Format: {requirements.delivery_format}")
    print(f"   - Cohort: {feasibility.estimated_cohort_size}")

    # Route to delivery_agent
    try:
        await orchestrator.route_task(
            agent_id="delivery_agent",
            task="deliver_data",
            context=context,
            from_agent="recovery_script",
        )
        print(f"✅ Successfully routed to delivery_agent!")
        print(f"\n📦 Check Admin Dashboard for delivery status")
        return 0
    except Exception as e:
        print(f"❌ Failed to route to delivery_agent: {str(e)}")
        import traceback

        traceback.print_exc()
        return 1


async def main():
    request_id = "REQ-20251106-D710278F"

    print("=" * 70)
    print("📦 Trigger Delivery for Stuck Request")
    print("=" * 70)
    print(f"Request ID: {request_id}")
    print("=" * 70)

    exit_code = await trigger_delivery(request_id)
    return exit_code


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
