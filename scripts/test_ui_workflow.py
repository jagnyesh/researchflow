"""
Test complete workflow as if submitted through Researcher Portal
and approved through Admin Dashboard
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
from app.database.models import ResearchRequest, Approval
from sqlalchemy import select


async def submit_request():
    """Simulate submitting a request through Researcher Portal"""
    print("\n" + "=" * 80)
    print("STEP 1: Submitting request (simulating Researcher Portal)")
    print("=" * 80 + "\n")

    # Initialize orchestrator with agents (same as Admin Dashboard does)
    orchestrator = ResearchRequestOrchestrator()

    hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")
    if "postgresql://" in hapi_db_url and "+asyncpg" not in hapi_db_url:
        hapi_db_url_async = hapi_db_url.replace("postgresql://", "postgresql+asyncpg://")
    else:
        hapi_db_url_async = hapi_db_url

    orchestrator.register_agent("requirements_agent", RequirementsAgent())
    orchestrator.register_agent(
        "phenotype_agent", PhenotypeValidationAgent(database_url=hapi_db_url_async)
    )
    orchestrator.register_agent(
        "extraction_agent", DataExtractionAgent(database_url=hapi_db_url_async)
    )
    orchestrator.register_agent("qa_agent", QualityAssuranceAgent())
    orchestrator.register_agent("delivery_agent", DeliveryAgent())

    # Submit request
    researcher_info = {
        "name": "UI Test User",
        "email": "uitest@hospital.org",
        "department": "Testing",
        "irb_number": "IRB-UI-TEST-001",
    }

    researcher_request = """
    I need demographics (family name, given name, date of birth, address) for
    male patients with diabetes diagnosis.
    """

    request_id = await orchestrator.process_new_request(
        researcher_request=researcher_request,
        researcher_info=researcher_info,
        from_formal_portal=True,
    )

    print(f"✅ Request submitted: {request_id}")
    return request_id, orchestrator


async def wait_and_check_approvals(request_id: str):
    """Wait for approvals to appear"""
    print(f"\n" + "=" * 80)
    print(f"STEP 2: Waiting for approvals to appear...")
    print("=" * 80 + "\n")

    for i in range(10):  # Wait up to 20 seconds
        await asyncio.sleep(2)

        async with get_db_session() as session:
            result = await session.execute(
                select(Approval)
                .where(Approval.request_id == request_id)
                .where(Approval.status == "pending")
            )
            pending = result.scalars().all()

            if pending:
                print(f"\n✅ Found {len(pending)} pending approval(s):")
                for approval in pending:
                    print(f"   - {approval.approval_type} (ID: {approval.id})")
                return [a.id for a in pending]

        print(f"   Waiting... ({i+1}/10)")

    print(f"\n❌ No pending approvals found after 20 seconds")
    return []


async def approve_all(request_id: str, orchestrator):
    """Approve all pending approvals (simulating Admin Dashboard)"""
    print(f"\n" + "=" * 80)
    print(f"STEP 3: Approving all pending approvals (simulating Admin Dashboard)")
    print("=" * 80 + "\n")

    max_iterations = 10
    for iteration in range(max_iterations):
        async with get_db_session() as session:
            result = await session.execute(
                select(Approval)
                .where(Approval.request_id == request_id)
                .where(Approval.status == "pending")
            )
            pending = result.scalars().all()

        if not pending:
            print(f"\n✅ No more pending approvals")
            break

        print(f"\nIteration {iteration + 1}: Found {len(pending)} pending approval(s)")

        for approval in pending:
            print(f"   Approving {approval.approval_type} (ID: {approval.id})...")

            # Call orchestrator.process_approval_response (same as Admin Dashboard)
            await orchestrator.process_approval_response(
                approval_id=approval.id,
                reviewer="ui_test_script",
                decision="approve",
                notes="Auto-approved by UI test script",
            )

            print(f"   ✅ Approved!")

        # Wait a bit for workflow to progress
        await asyncio.sleep(3)

    if iteration >= max_iterations - 1:
        print(f"\n⚠️ Reached max iterations ({max_iterations})")


async def check_final_state(request_id: str):
    """Check final state of request"""
    print(f"\n" + "=" * 80)
    print(f"STEP 4: Checking final state")
    print("=" * 80 + "\n")

    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        if not request:
            print(f"❌ Request not found!")
            return False

        print(f"Request ID: {request.id}")
        print(f"State: {request.current_state}")
        print(f"Agent: {request.current_agent}")
        print(f"Created: {request.created_at}")
        print(f"Updated: {request.updated_at}")
        print(f"Completed: {request.completed_at}")

        if request.current_state == "complete":
            print(f"\n✅ ✅ ✅ WORKFLOW COMPLETED SUCCESSFULLY! ✅ ✅ ✅")
            return True
        else:
            print(f"\n❌ Workflow did NOT complete. Stuck in state: {request.current_state}")
            return False


async def main():
    print("\n" + "=" * 80)
    print("UI WORKFLOW TEST")
    print("Testing complete workflow as if submitted through Researcher Portal")
    print("and approved through Admin Dashboard")
    print("=" * 80)

    # Step 1: Submit request
    request_id, orchestrator = await submit_request()

    # Step 2: Wait for approvals
    approval_ids = await wait_and_check_approvals(request_id)

    # Step 3: Approve all
    await approve_all(request_id, orchestrator)

    # Step 4: Check final state
    success = await check_final_state(request_id)

    if success:
        print(f"\n{'='*80}")
        print(f"✅ TEST PASSED - Workflow works end-to-end!")
        print(f"{'='*80}\n")
        return 0
    else:
        print(f"\n{'='*80}")
        print(f"❌ TEST FAILED - Workflow did not complete")
        print(f"{'='*80}\n")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
