"""
Manual Approval Test Script

Tests approving a pending approval and resuming the LangGraph workflow.
"""

import asyncio
import logging
import os

# Set database URL to PostgreSQL (same as .env)
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://researchflow:researchflow@localhost:5434/researchflow"
)

from app.langchain_orchestrator.request_facade import LangGraphRequestFacade
from app.database import get_db_session
from app.database.models import Approval, ResearchRequest
from sqlalchemy import select

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_approval():
    """Test approving pending approval ID 122"""

    # Initialize facade
    facade = LangGraphRequestFacade(use_real_agents=True, use_persistence=True)

    # Get pending approval
    async with get_db_session() as session:
        result = await session.execute(select(Approval).where(Approval.id == 122))
        approval = result.scalar_one_or_none()

        if not approval:
            print("❌ Approval 122 not found!")
            return

        print(f"✅ Found approval 122:")
        print(f"   Request ID: {approval.request_id}")
        print(f"   Type: {approval.approval_type}")
        print(f"   Status: {approval.status}")
        print(f"   Submitted by: {approval.submitted_by}")
        print()

        # Get request state before approval
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == approval.request_id)
        )
        request = result.scalar_one_or_none()

        if request:
            print(f"📊 Request state BEFORE approval:")
            print(f"   Current state: {request.current_state}")
            print(f"   Current agent: {request.current_agent}")
            print()

    # Process approval
    print("🔄 Processing approval (approving)...")
    try:
        await facade.process_approval_response(
            approval_id=122,
            reviewer="test_script",
            decision="approve",
            notes="Manual test approval",
        )
        print("✅ Approval processed successfully!")
    except Exception as e:
        print(f"❌ Error processing approval: {e}")
        import traceback

        traceback.print_exc()
        return

    # Check request state after approval
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == approval.request_id)
        )
        request = result.scalar_one_or_none()

        if request:
            print()
            print(f"📊 Request state AFTER approval:")
            print(f"   Current state: {request.current_state}")
            print(f"   Current agent: {request.current_agent}")
            print(f"   State history: {request.state_history}")
            print()

            if request.current_state != "phenotype_review":
                print("✅ SUCCESS! Workflow progressed beyond phenotype_review!")
            else:
                print("❌ FAILED! Workflow still stuck at phenotype_review")

        # Check approval status
        result = await session.execute(select(Approval).where(Approval.id == 122))
        approval = result.scalar_one_or_none()

        if approval:
            print(f"📋 Approval status after processing:")
            print(f"   Status: {approval.status}")
            print(f"   Reviewed by: {approval.reviewed_by}")

    await facade.close()


if __name__ == "__main__":
    asyncio.run(test_approval())
