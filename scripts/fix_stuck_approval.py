#!/usr/bin/env python3
"""
Fix Stuck Approval - Manually Trigger Workflow Continuation

This script manually triggers workflow continuation for requests stuck after approval.
Use this when an approval was marked "approved" in the database but the workflow didn't continue.

Usage:
    python scripts/fix_stuck_approval.py
    python scripts/fix_stuck_approval.py --request-id REQ-20251104-1EF0777A
"""

import asyncio
import sys
import os
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import select
from app.database import get_db_session
from app.database.models import Approval, ResearchRequest
from app.orchestrator import ResearchRequestOrchestrator
from app.agents import (
    RequirementsAgent,
    PhenotypeValidationAgent,
    CalendarAgent,
    DataExtractionAgent,
    QualityAssuranceAgent,
    DeliveryAgent,
)


async def fix_stuck_approval(request_id: str):
    """
    Manually trigger workflow continuation for a stuck approved request

    Args:
        request_id: Research request ID
    """
    print(f"\n{'='*80}")
    print(f"Fixing Stuck Approval for Request: {request_id}")
    print(f"{'='*80}\n")

    # Initialize orchestrator with all agents
    print("🔧 Initializing orchestrator...")
    orchestrator = ResearchRequestOrchestrator()
    hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")

    orchestrator.register_agent("requirements_agent", RequirementsAgent())
    orchestrator.register_agent(
        "phenotype_agent", PhenotypeValidationAgent(database_url=hapi_db_url)
    )
    orchestrator.register_agent("calendar_agent", CalendarAgent())
    orchestrator.register_agent("extraction_agent", DataExtractionAgent())
    orchestrator.register_agent("qa_agent", QualityAssuranceAgent())
    orchestrator.register_agent("delivery_agent", DeliveryAgent())

    print("✓ Orchestrator initialized\n")

    # Find approved approval for this request
    async with get_db_session() as session:
        # Get request info
        req_result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = req_result.scalar_one_or_none()

        if not request:
            print(f"❌ ERROR: Request {request_id} not found in database")
            return False

        print(f"✓ Found request: {request.id}")
        print(f"  Researcher: {request.researcher_name}")
        print(f"  Current State: {request.current_state}")
        print(f"  Current Agent: {request.current_agent}")
        print(f"  Created: {request.created_at}")

        # Determine which approval type to look for based on current state
        approval_type_map = {
            "requirements_review": "requirements",
            "phenotype_review": "phenotype_sql",
            "extraction_approval": "extraction",
            "delivery_review": "delivery",
        }

        approval_type = approval_type_map.get(request.current_state)

        if not approval_type:
            print(f"\n⚠️  WARNING: Current state '{request.current_state}' is not an approval state")
            print("This script only works for requests stuck in approval states.")
            return False

        print(f"\n📝 Looking for approved '{approval_type}' approval...")

        # Find the approved approval
        result = await session.execute(
            select(Approval)
            .where(Approval.request_id == request_id)
            .where(Approval.approval_type == approval_type)
            .where(Approval.status == "approved")
            .order_by(Approval.reviewed_at.desc())
            .limit(1)
        )
        approval = result.scalar_one_or_none()

        if not approval:
            print(f"❌ No approved '{approval_type}' approval found for {request_id}")
            print("\nPossible reasons:")
            print("  1. The approval hasn't been approved yet")
            print("  2. The approval was rejected")
            print("  3. The approval type doesn't match the current state")
            return False

        print(f"\n✅ Found approved approval:")
        print(f"   - Approval ID: {approval.id}")
        print(f"   - Approval Type: {approval.approval_type}")
        print(f"   - Status: {approval.status}")
        print(f"   - Submitted By: {approval.submitted_by}")
        print(f"   - Submitted At: {approval.submitted_at}")
        print(f"   - Reviewed By: {approval.reviewed_by}")
        print(f"   - Reviewed At: {approval.reviewed_at}")

    # Manually trigger workflow continuation
    print(f"\n🔄 Triggering workflow continuation...")
    print(f"   Calling: orchestrator.process_approval_response()")

    try:
        await orchestrator.process_approval_response(
            approval_id=approval.id,
            reviewer="fix_stuck_approval_script",
            decision="approve",
            notes="Manually triggered workflow continuation via fix_stuck_approval.py script",
        )

        print(f"\n{'='*80}")
        print(f"✅ SUCCESS! Workflow continuation triggered")
        print(f"{'='*80}")
        print(f"\nThe workflow should now advance to the next agent.")
        print(f"Check the Admin Dashboard to verify the request has moved forward.")
        print(f"{'='*80}\n")

        return True

    except Exception as e:
        print(f"\n❌ ERROR triggering workflow continuation:")
        print(f"   {str(e)}")
        import traceback

        print("\nFull traceback:")
        print(traceback.format_exc())
        return False


async def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Fix stuck approval by manually triggering workflow continuation"
    )
    parser.add_argument(
        "--request-id",
        type=str,
        default="REQ-20251104-1EF0777A",
        help="Research request ID (default: REQ-20251104-1EF0777A)",
    )

    args = parser.parse_args()

    success = await fix_stuck_approval(args.request_id)

    if success:
        print("✓ Fixed successfully")
        sys.exit(0)
    else:
        print("✗ Failed to fix")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
