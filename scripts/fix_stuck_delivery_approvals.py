#!/usr/bin/env python3
"""
Backfill script to fix stuck requests with approved delivery approvals

This script finds requests that have:
- Status: human_review (stuck)
- Approved delivery approval in database
- But workflow never continued to delivery_agent

Root cause: The delivery approval button in admin_dashboard.py was calling
approve_delivery() directly instead of process_approval_response(), which
meant the orchestrator never routed to delivery_agent after approval.

This script manually triggers the workflow continuation for those stuck requests.

Usage:
    python scripts/fix_stuck_delivery_approvals.py [--dry-run]
"""

import asyncio
import sys
import os
from datetime import datetime
from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db_session
from app.database.models import ResearchRequest, Approval
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade


async def find_stuck_requests():
    """Find requests stuck in human_review with approved delivery approvals"""
    print("\n🔍 Searching for stuck requests...")

    async with get_db_session() as session:
        # Find requests in human_review state
        result = await session.execute(
            select(ResearchRequest.id, ResearchRequest.current_agent)
            .where(ResearchRequest.current_state == "human_review")
            .where(ResearchRequest.completed_at.is_(None))
        )
        human_review_requests = result.all()

        stuck_requests = []

        for req_id, current_agent in human_review_requests:
            # Check if there's an approved delivery approval
            approval_result = await session.execute(
                select(Approval)
                .where(Approval.request_id == req_id)
                .where(Approval.approval_type == "delivery")
                .where(Approval.status == "approved")
            )
            delivery_approval = approval_result.scalar_one_or_none()

            if delivery_approval:
                # This request has approved delivery but is stuck
                stuck_requests.append(
                    {
                        "request_id": req_id,
                        "current_agent": current_agent,
                        "approval_id": delivery_approval.id,
                        "approved_at": delivery_approval.reviewed_at,
                        "approved_by": delivery_approval.reviewed_by,
                    }
                )

    return stuck_requests


async def fix_stuck_request(orchestrator, request_id, approval_id, approval_info):
    """Manually trigger workflow continuation for a stuck request"""
    print(f"\n🔧 Fixing request {request_id}...")
    print(f"   Approval ID: {approval_id}")
    print(f"   Approved at: {approval_info['approved_at']}")
    print(f"   Approved by: {approval_info['approved_by']}")

    try:
        # Sprint 7.2: A2A's private _continue_workflow_after_approval() was the
        # original target; LangGraph's process_approval_response() is the
        # production-supported API and persists + resumes from checkpoint.
        # Idempotent on already-approved approvals (re-emits the resume signal).
        await orchestrator.process_approval_response(
            approval_id=approval_id,
            reviewer="fix_stuck_delivery_approvals_script",
            decision="approve",
            notes="Backfill via scripts/fix_stuck_delivery_approvals.py",
        )

        print(f"   ✅ Successfully triggered workflow continuation")
        return True

    except Exception as e:
        print(f"   ❌ Failed to fix: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Main backfill workflow"""
    import argparse

    parser = argparse.ArgumentParser(description="Fix stuck delivery approvals")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be fixed without making changes"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("🔧 Backfill Script: Fix Stuck Delivery Approvals")
    print("=" * 70)
    print(f"Mode: {'DRY RUN (no changes)' if args.dry_run else 'LIVE (will make changes)'}")
    print("=" * 70)

    # Find stuck requests
    stuck_requests = await find_stuck_requests()

    if not stuck_requests:
        print("\n✅ No stuck requests found!")
        print("\nAll requests with approved delivery approvals have proceeded correctly.")
        return 0

    print(f"\n📊 Found {len(stuck_requests)} stuck request(s):")
    print("-" * 70)

    for i, req in enumerate(stuck_requests, 1):
        print(f"\n{i}. Request: {req['request_id']}")
        print(f"   Current Agent: {req['current_agent']}")
        print(f"   Approval ID: {req['approval_id']}")
        print(f"   Approved at: {req['approved_at']}")
        print(f"   Approved by: {req['approved_by']}")

    if args.dry_run:
        print("\n" + "=" * 70)
        print("🔍 DRY RUN COMPLETE - No changes made")
        print("=" * 70)
        print(f"\nTo fix these {len(stuck_requests)} request(s), run:")
        print(f"    python scripts/fix_stuck_delivery_approvals.py")
        return 0

    print("\n" + "=" * 70)
    print("🚀 Starting backfill process...")
    print("=" * 70)

    # Initialize LangGraph facade (Sprint 7.2: A2A orchestrator deleted in Phase 4).
    orchestrator = LangGraphRequestFacade(use_real_agents=True, use_persistence=True)
    print("✅ LangGraph facade initialized")

    # Fix each stuck request
    fixed_count = 0
    failed_count = 0

    for req in stuck_requests:
        success = await fix_stuck_request(
            orchestrator,
            req["request_id"],
            req["approval_id"],
            {"approved_at": req["approved_at"], "approved_by": req["approved_by"]},
        )

        if success:
            fixed_count += 1
        else:
            failed_count += 1

    # Summary
    print("\n" + "=" * 70)
    print("📊 BACKFILL COMPLETE")
    print("=" * 70)
    print(f"Total requests processed: {len(stuck_requests)}")
    print(f"✅ Successfully fixed: {fixed_count}")
    print(f"❌ Failed to fix: {failed_count}")

    if fixed_count > 0:
        print("\n✅ Next steps:")
        print("   1. Check Admin Dashboard for delivery_agent executions")
        print("   2. Verify DataDelivery records created")
        print("   3. Check /data/deliveries/{request_id}/ for files")
        print("   4. Monitor logs for any errors")

    if failed_count > 0:
        print("\n⚠️  Some requests failed to fix. Check logs above for errors.")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
