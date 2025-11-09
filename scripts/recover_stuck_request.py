#!/usr/bin/env python3
"""
Recovery script for stuck request REQ-20251106-D710278F

This request has agent execution results but no persisted data in
requirements_data or feasibility_reports tables. This script:
1. Extracts data from agent_executions.result JSON
2. Creates missing database records
3. Manually triggers delivery_agent
"""

import asyncio
import json
import sys
from datetime import datetime
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, "/Users/jagnyesh/Development/FHIR_PROJECT")

from app.database import get_db_session
from app.database.models import ResearchRequest, RequirementsData, FeasibilityReport, AgentExecution
from app.orchestrator.orchestrator import ResearchRequestOrchestrator
from app.agents.requirements_agent import RequirementsAgent
from app.agents.phenotype_agent import PhenotypeValidationAgent
from app.agents.calendar_agent import CalendarAgent
from app.agents.extraction_agent import DataExtractionAgent
from app.agents.qa_agent import QualityAssuranceAgent
from app.agents.delivery_agent import DeliveryAgent
import os


async def extract_agent_results(session: AsyncSession, request_id: str) -> dict:
    """Extract structured_requirements and phenotype_sql from agent execution results"""

    print(f"\n📊 Extracting agent results for {request_id}...")

    # Get requirements_agent result
    result = await session.execute(
        select(AgentExecution)
        .where(AgentExecution.request_id == request_id)
        .where(AgentExecution.agent_id == "requirements_agent")
        .where(AgentExecution.task == "gather_requirements")
        .order_by(AgentExecution.created_at.desc())
    )
    req_execution = result.scalar_one_or_none()

    if not req_execution:
        print("❌ No requirements_agent execution found")
        return None

    requirements_result = req_execution.result
    structured_requirements = requirements_result.get("structured_requirements")

    if not structured_requirements:
        print("❌ No structured_requirements in agent result")
        return None

    print(f"✅ Found structured_requirements:")
    print(f"   - Study: {structured_requirements.get('study_title')}")
    print(f"   - PI: {structured_requirements.get('principal_investigator')}")
    print(f"   - Inclusion criteria: {len(structured_requirements.get('inclusion_criteria', []))}")
    print(f"   - Data elements: {len(structured_requirements.get('data_elements', []))}")

    # Get phenotype_agent result
    result = await session.execute(
        select(AgentExecution)
        .where(AgentExecution.request_id == request_id)
        .where(AgentExecution.agent_id == "phenotype_agent")
        .where(AgentExecution.task == "validate_feasibility")
        .order_by(AgentExecution.created_at.desc())
    )
    pheno_execution = result.scalar_one_or_none()

    if not pheno_execution:
        print("❌ No phenotype_agent execution found")
        return None

    phenotype_result = pheno_execution.result
    phenotype_sql = phenotype_result.get("phenotype_sql")
    feasibility_report = phenotype_result.get("feasibility_report", {})

    if not phenotype_sql:
        print("❌ No phenotype_sql in agent result")
        return None

    print(f"✅ Found phenotype_sql:")
    print(f"   - Estimated cohort: {phenotype_result.get('estimated_cohort_size')}")
    print(f"   - Feasibility score: {phenotype_result.get('feasibility_score')}")
    print(f"   - SQL preview: {phenotype_sql[:100]}...")

    return {
        "structured_requirements": structured_requirements,
        "phenotype_sql": phenotype_sql,
        "feasibility_report": feasibility_report,
        "estimated_cohort_size": phenotype_result.get("estimated_cohort_size", 0),
        "feasibility_score": phenotype_result.get("feasibility_score", 0.0),
    }


async def create_missing_records(session: AsyncSession, request_id: str, data: dict):
    """Create missing requirements_data and feasibility_reports records"""

    print(f"\n📝 Creating missing database records...")

    # Create requirements_data record
    req = data["structured_requirements"]
    requirements_data = RequirementsData(
        request_id=request_id,
        created_at=datetime.utcnow(),
        study_title=req.get("study_title"),
        principal_investigator=req.get("principal_investigator"),
        irb_number=req.get("irb_number"),
        inclusion_criteria=req.get("inclusion_criteria"),
        exclusion_criteria=req.get("exclusion_criteria"),
        data_elements=req.get("data_elements"),
        time_period_start=None,  # Not specified in this request
        time_period_end=None,
        estimated_cohort_size=data.get("estimated_cohort_size"),
        minimum_cohort_size=50,  # Default from requirements
        delivery_format=req.get("delivery_format"),
        phi_level=req.get("phi_level"),
        completeness_score=1.0,
        is_complete=True,
    )
    session.add(requirements_data)
    print(f"✅ Created requirements_data record")

    # Create feasibility_reports record
    fr = data["feasibility_report"]
    feasibility_report = FeasibilityReport(
        request_id=request_id,
        created_at=datetime.utcnow(),
        is_feasible=fr.get("feasible", False),
        feasibility_score=data.get("feasibility_score", 0.0),
        estimated_cohort_size=data.get("estimated_cohort_size"),
        confidence_interval_low=fr.get("confidence_interval", [0, 0])[0],
        confidence_interval_high=fr.get("confidence_interval", [0, 0])[1],
        data_availability=fr.get("data_availability"),
        overall_availability=fr.get("data_availability", {}).get("overall_availability", 0.0),
        phenotype_sql=data["phenotype_sql"],
        estimated_extraction_time_hours=fr.get("estimated_extraction_time_hours", 2.0),
        warnings=fr.get("warnings"),
        recommendations=fr.get("recommendations"),
    )
    session.add(feasibility_report)
    print(f"✅ Created feasibility_reports record")

    await session.commit()
    print(f"✅ Database records committed")


async def trigger_delivery_agent(request_id: str):
    """Manually trigger delivery_agent with proper context"""

    print(f"\n🚀 Triggering delivery_agent...")

    # Initialize orchestrator and register all agents
    orchestrator = ResearchRequestOrchestrator()

    # Get HAPI FHIR database URL from environment
    hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")

    # Convert to asyncpg format for SQLAlchemy async engine
    if "postgresql://" in hapi_db_url and "+asyncpg" not in hapi_db_url:
        hapi_db_url_async = hapi_db_url.replace("postgresql://", "postgresql+asyncpg://")
    else:
        hapi_db_url_async = hapi_db_url

    # Register all agents (including delivery_agent)
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

    print(f"✅ Registered 6 agents including delivery_agent")

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

    # Build context with all required fields
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

    print(f"✅ Built context with {len(context)} top-level keys")
    print(f"   - structured_requirements: {len(context['structured_requirements'])} fields")
    print(f"   - phenotype_sql: {len(context['phenotype_sql'])} chars")

    # Route to delivery_agent
    try:
        await orchestrator.route_task(
            agent_id="delivery_agent",
            task="deliver_data",
            context=context,
            from_agent="recovery_script",
        )
        print(f"✅ Successfully routed to delivery_agent")
    except Exception as e:
        print(f"❌ Failed to route to delivery_agent: {str(e)}")
        raise


async def main():
    """Main recovery workflow"""

    request_id = "REQ-20251106-D710278F"

    print("=" * 70)
    print("🔧 Recovery Script for Stuck Request")
    print("=" * 70)
    print(f"Request ID: {request_id}")
    print(f"Issue: Agent results not persisted to database tables")
    print(f"Fix: Extract from agent_executions and create missing records")
    print("=" * 70)

    try:
        # Step 1: Extract data from agent executions
        async with get_db_session() as session:
            data = await extract_agent_results(session, request_id)

        if not data:
            print("\n❌ Failed to extract agent results")
            return 1

        # Step 2: Create missing database records
        async with get_db_session() as session:
            await create_missing_records(session, request_id, data)

        # Step 3: Trigger delivery_agent
        await trigger_delivery_agent(request_id)

        print("\n" + "=" * 70)
        print("✅ Recovery completed successfully!")
        print("=" * 70)
        print(f"\nNext steps:")
        print(f"1. Check Admin Dashboard for delivery_agent execution")
        print(f"2. Verify DataDelivery record created")
        print(f"3. Check /data/deliveries/{request_id}/ for files")
        print(f"4. Download CSV from Researcher Portal")

        return 0

    except Exception as e:
        print(f"\n❌ Recovery failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
