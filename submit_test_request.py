#!/usr/bin/env python3
"""Submit a test research request to trigger LangGraph workflow"""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


async def submit_test_request():
    """Submit a test research request"""
    from app.database import get_db_session
    from app.orchestrator.orchestrator import ResearchRequestOrchestrator

    print("=" * 80)
    print("Submitting Test Research Request")
    print("=" * 80)

    orchestrator = ResearchRequestOrchestrator()

    request_data = {
        "researcher_name": "Test Researcher",
        "researcher_email": "test@example.com",
        "irb_number": "IRB-TEST-2025",
        "initial_request": "I need demographics (family name, given name, date of birth) for female patients with hypertension.",
        "phi_level": "de_identified",
    }

    print("\nSubmitting request...")
    request_id = await orchestrator.submit_request(request_data)
    print(f"✅ Request submitted: {request_id}")

    # Wait for requirements gathering (auto-agent)
    print("\nWaiting for requirements gathering...")
    await asyncio.sleep(5)

    # Check state
    async with get_db_session() as session:
        from app.database.models import ResearchRequest, Approval
        from sqlalchemy import select

        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()
        print(f"Current state: {request.current_state}")
        print(f"Current agent: {request.current_agent}")

        # Check for pending approval
        result = await session.execute(
            select(Approval)
            .where(Approval.request_id == request_id)
            .where(Approval.status == "pending")
        )
        pending_approval = result.scalar_one_or_none()

        if pending_approval:
            print(f"\n✅ Pending approval created:")
            print(f"   Approval ID: {pending_approval.id}")
            print(f"   Type: {pending_approval.approval_type}")
            print(f"\nNow you can test approving this in the admin dashboard!")
            return request_id, pending_approval.id
        else:
            print("\n⚠️  No pending approval found yet - workflow may still be running")
            return request_id, None


if __name__ == "__main__":
    request_id, approval_id = asyncio.run(submit_test_request())
    print(f"\nRequest ID: {request_id}")
    if approval_id:
        print(f"Approval ID: {approval_id}")
