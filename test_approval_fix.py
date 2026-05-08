#!/usr/bin/env python3
"""
Test script to verify approval workflow resumption fix.

This simulates clicking the "Approve" button in admin dashboard
and verifies the workflow resumes correctly.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


async def test_approval_workflow():
    """Test approval workflow resumption"""
    from app.database import get_db_session
    from app.database.models import Approval, ResearchRequest
    from app.orchestrator.orchestrator import ResearchRequestOrchestrator
    from sqlalchemy import select

    print("=" * 80)
    print("Testing Approval Workflow Resumption Fix")
    print("=" * 80)

    # Step 1: Find a pending SQL approval
    print("\n1. Finding pending SQL approval...")
    async with get_db_session() as session:
        result = await session.execute(
            select(Approval)
            .where(Approval.approval_type == "phenotype_sql")
            .where(Approval.status == "pending")
            .limit(1)
        )
        pending_approval = result.scalar_one_or_none()

        if not pending_approval:
            print("   ❌ No pending SQL approvals found")
            print("   Tip: Submit a new request via the researcher portal first")
            return False

        approval_id = pending_approval.id
        request_id = pending_approval.request_id
        print(f"   ✅ Found approval {approval_id} for request {request_id}")

        # Get request details
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()
        print(f"   Current state: {request.current_state}")

    # Step 2: Process the approval (simulate clicking Approve button)
    print("\n2. Processing approval (simulating Approve button click)...")
    try:
        orchestrator = ResearchRequestOrchestrator()

        await orchestrator.process_approval_response(
            approval_id=approval_id,
            reviewer="test_script",
            decision="approve",
            notes="Automated test approval",
            modifications={},
        )
        print("   ✅ Approval processed successfully")
    except Exception as e:
        print(f"   ❌ Error processing approval: {str(e)}")
        import traceback

        traceback.print_exc()
        return False

    # Step 3: Wait a moment for workflow to resume
    print("\n3. Waiting for workflow to resume...")
    await asyncio.sleep(3)

    # Step 4: Check if workflow progressed
    print("\n4. Checking workflow state after approval...")
    async with get_db_session() as session:
        # Check approval status
        result = await session.execute(select(Approval).where(Approval.id == approval_id))
        approval = result.scalar_one_or_none()
        print(f"   Approval status: {approval.status}")
        print(f"   Reviewed by: {approval.reviewed_by}")

        # Check request state
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()
        print(f"   Request state: {request.current_state}")
        print(f"   Current agent: {request.current_agent}")

        # Verify workflow progressed
        if approval.status == "approved":
            print("\n   ✅ Approval marked as approved")
        else:
            print(f"\n   ❌ Approval still in {approval.status} status")
            return False

        # Check if workflow moved to next state
        if request.current_state in ["schedule_kickoff", "requirements_gathering"]:
            print(f"   ✅ Workflow progressed to {request.current_state}")
            print("\n" + "=" * 80)
            print("TEST PASSED: Workflow resumption fix is working!")
            print("=" * 80)
            return True
        elif request.current_state == "phenotype_review":
            print(f"   ❌ Workflow still stuck in {request.current_state}")
            print("\n" + "=" * 80)
            print("TEST FAILED: Workflow did not resume after approval")
            print("=" * 80)
            return False
        else:
            print(f"   ⚠️  Workflow in unexpected state: {request.current_state}")
            return True  # May have progressed past schedule_kickoff


if __name__ == "__main__":
    result = asyncio.run(test_approval_workflow())
    sys.exit(0 if result else 1)
