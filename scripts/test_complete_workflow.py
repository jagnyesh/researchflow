"""
Test complete workflow from request submission through preview extraction

This will:
1. Create a new request
2. Auto-approve all steps
3. Monitor the workflow progression
4. Identify where it gets stuck
"""

import asyncio
import sys
import os
from datetime import datetime
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.orchestrator import ResearchRequestOrchestrator
from app.agents import (
    RequirementsAgent,
    PhenotypeValidationAgent,
    DataExtractionAgent,
    QualityAssuranceAgent,
    DeliveryAgent,
)
from app.database import get_db_session
from app.database.models import ResearchRequest, Approval, AgentExecution
from sqlalchemy import select


async def monitor_request(request_id: str, orchestrator, duration_seconds: int = 30):
    """Monitor request for specified duration and auto-approve pending approvals"""
    start_time = time.time()
    prev_state = None
    prev_agent = None

    print(f"\n{'='*80}")
    print(f"MONITORING REQUEST: {request_id}")
    print(f"Duration: {duration_seconds} seconds")
    print(f"{'='*80}\n")

    while time.time() - start_time < duration_seconds:
        # Check for pending approvals FIRST (outside session)
        pending_approval_ids = []
        async with get_db_session() as session:
            result = await session.execute(
                select(Approval)
                .where(Approval.request_id == request_id)
                .where(Approval.status == "pending")
            )
            pending_approvals = result.scalars().all()

            for approval in pending_approvals:
                pending_approval_ids.append((approval.id, approval.approval_type))

        # Process approvals OUTSIDE of the session (so orchestrator can create its own sessions)
        for approval_id, approval_type in pending_approval_ids:
            print(f"   ⏳ PENDING APPROVAL: {approval_type} (ID: {approval_id})")
            print(f"      Auto-approving and continuing workflow...")

            # This will both approve AND trigger the next workflow step
            await orchestrator.process_approval_response(
                approval_id=approval_id,
                reviewer="test_script",
                decision="approve",
                notes="Auto-approved by test script",
            )
            print(f"      ✅ Approved and workflow continued!")

        # Now check request state
        async with get_db_session() as session:
            # Get request
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            request = result.scalar_one_or_none()

            if not request:
                print(f"❌ Request {request_id} not found!")
                return

            # Check for state changes
            current_state = request.current_state
            current_agent = request.current_agent

            if current_state != prev_state or current_agent != prev_agent:
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] State: {current_state}, Agent: {current_agent}")
                prev_state = current_state
                prev_agent = current_agent

            # Check for failed executions
            result = await session.execute(
                select(AgentExecution)
                .where(AgentExecution.request_id == request_id)
                .where(AgentExecution.status == "failed")
            )
            failed_executions = result.scalars().all()

            if failed_executions:
                for execution in failed_executions:
                    print(f"   ❌ FAILED: {execution.agent_id}.{execution.task}")
                    print(f"      Error: {execution.error}")

        await asyncio.sleep(2)  # Check every 2 seconds

    print(f"\n{'='*80}")
    print(f"MONITORING COMPLETE")
    print(f"{'='*80}\n")


async def test_workflow():
    """Test complete workflow"""
    print("\n" + "=" * 80)
    print("WORKFLOW TEST: Creating new request and monitoring progress")
    print("=" * 80 + "\n")

    # Initialize orchestrator
    orchestrator = ResearchRequestOrchestrator()

    # Get HAPI database URL
    hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")
    if "postgresql://" in hapi_db_url and "+asyncpg" not in hapi_db_url:
        hapi_db_url_async = hapi_db_url.replace("postgresql://", "postgresql+asyncpg://")
    else:
        hapi_db_url_async = hapi_db_url

    # Register agents
    orchestrator.register_agent("requirements_agent", RequirementsAgent())
    orchestrator.register_agent(
        "phenotype_agent", PhenotypeValidationAgent(database_url=hapi_db_url_async)
    )
    orchestrator.register_agent(
        "extraction_agent", DataExtractionAgent(database_url=hapi_db_url_async)
    )
    orchestrator.register_agent("qa_agent", QualityAssuranceAgent())
    orchestrator.register_agent("delivery_agent", DeliveryAgent())

    # Create test request
    researcher_info = {
        "name": "Test Workflow User",
        "email": "workflow_test@hospital.org",
        "department": "Testing Department",
        "irb_number": "IRB-WORKFLOW-TEST-001",
    }

    researcher_request = """
    I need data for patients with diabetes (ICD-10: E11) diagnosed in the last year.

    Inclusion criteria:
    - Adults (age >= 18)
    - Diagnosed with Type 2 Diabetes (E11.*)
    - Diagnosis within last 12 months

    Exclusion criteria:
    - Pediatric patients (age < 18)

    Data elements needed:
    - Demographics (age, gender)
    - Lab results (HbA1c, glucose)
    - Medications

    PHI level: De-identified
    Delivery format: CSV
    """

    print(f"Creating request...")
    request_id = await orchestrator.process_new_request(
        researcher_request=researcher_request,
        researcher_info=researcher_info,
        from_formal_portal=True,  # Use form-based mode (skip conversational)
    )

    print(f"✅ Request created: {request_id}")
    print(f"Starting monitoring...")

    # Monitor for 60 seconds
    await monitor_request(request_id, orchestrator, duration_seconds=60)

    # Final status
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        print(f"\nFINAL STATUS:")
        print(f"  State: {request.current_state}")
        print(f"  Agent: {request.current_agent}")
        print(f"  Completed: {request.completed_at}")

        # Get all approvals
        result = await session.execute(select(Approval).where(Approval.request_id == request_id))
        approvals = result.scalars().all()

        if approvals:
            print(f"\n  APPROVALS:")
            for approval in approvals:
                status_icon = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(
                    approval.status, "❓"
                )
                print(f"    {status_icon} {approval.approval_type}: {approval.status}")

        # Get all executions
        result = await session.execute(
            select(AgentExecution).where(AgentExecution.request_id == request_id)
        )
        executions = result.scalars().all()

        if executions:
            print(f"\n  AGENT EXECUTIONS:")
            for execution in executions:
                status_icon = {"success": "✅", "failed": "❌"}.get(execution.status, "❓")
                print(
                    f"    {status_icon} {execution.agent_id}.{execution.task}: {execution.status}"
                )


async def main():
    await test_workflow()


if __name__ == "__main__":
    asyncio.run(main())
