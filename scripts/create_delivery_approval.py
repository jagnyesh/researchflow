#!/usr/bin/env python3
"""
Create Missing Delivery Approval

This script creates a delivery approval record for requests stuck in DELIVERY_REVIEW state.
Use this to unblock requests that completed QA validation but didn't get an approval record.

Usage:
    python scripts/create_delivery_approval.py
    python scripts/create_delivery_approval.py --request-id REQ-20251104-A3DFF566
"""

import asyncio
import sys
import os
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import get_db_session
from app.database.models import ResearchRequest, DataDelivery
from app.services.approval_service import ApprovalService
from sqlalchemy import select


async def create_delivery_approval(request_id: str):
    """
    Create a delivery approval record for a request stuck in DELIVERY_REVIEW

    Args:
        request_id: Research request ID
    """
    print(f"\n{'='*80}")
    print(f"Creating Delivery Approval for Request: {request_id}")
    print(f"{'='*80}\n")

    async with get_db_session() as session:
        # Get request from database
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        if not request:
            print(f"❌ ERROR: Request {request_id} not found in database")
            return False

        print(f"✓ Found request: {request.id}")
        print(f"  Current State: {request.current_state}")
        print(f"  Current Agent: {request.current_agent}")
        print(f"  Researcher: {request.researcher_name}")

        # Check if already in delivery_review state
        if request.current_state != "delivery_review":
            print(f"\n⚠️  WARNING: Request is not in DELIVERY_REVIEW state")
            print(f"   Current state: {request.current_state}")
            print(f"   Expected: delivery_review")

            response = input("\nDo you want to continue anyway? (yes/no): ")
            if response.lower() not in ["yes", "y"]:
                print("Cancelled.")
                return False

        # Check if delivery approval already exists
        existing_approval = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        existing = existing_approval.scalar_one_or_none()

        # Get data delivery info if it exists
        delivery_result = await session.execute(
            select(DataDelivery).where(DataDelivery.request_id == request_id)
        )
        data_delivery = delivery_result.scalar_one_or_none()

        # Prepare approval data
        approval_data = {
            "request_id": request_id,
            "researcher_name": request.researcher_name,
            "current_state": request.current_state,
            "message": "Full data extraction complete and QA passed. Ready for delivery approval.",
            "timestamp": datetime.now().isoformat(),
        }

        if data_delivery:
            approval_data["data_delivery"] = {
                "format": data_delivery.format,
                "delivery_method": data_delivery.delivery_method,
                "file_path": data_delivery.file_path,
            }
            print(f"\n✓ Found data delivery record:")
            print(f"  Format: {data_delivery.format}")
            print(f"  Method: {data_delivery.delivery_method}")
        else:
            print(f"\n⚠️  No data delivery record found (will be created during delivery)")

        # Create approval service
        approval_service = ApprovalService(session)

        print(f"\n📝 Creating delivery approval...")

        # Create approval
        approval = await approval_service.create_approval(
            request_id=request_id,
            approval_type="delivery",
            submitted_by="qa_agent",
            approval_data=approval_data,
        )

        print(f"\n✅ SUCCESS! Delivery approval created")
        print(f"   Approval ID: {approval.id}")
        print(f"   Approval Type: {approval.approval_type}")
        print(f"   Status: {approval.status}")
        print(f"   Submitted By: {approval.submitted_by}")
        print(f"   Submitted At: {approval.submitted_at}")
        print(f"   Timeout At: {approval.timeout_at}")

        print(f"\n{'='*80}")
        print(f"Next Steps:")
        print(f"{'='*80}")
        print(f"1. Open Admin Dashboard: http://localhost:8502")
        print(f"2. Navigate to 'Pending Approvals' section")
        print(f"3. You should see the delivery approval for request {request_id}")
        print(f"4. Review and approve to continue the workflow")
        print(f"{'='*80}\n")

        return True


async def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Create missing delivery approval for stuck request"
    )
    parser.add_argument(
        "--request-id",
        type=str,
        default="REQ-20251104-A3DFF566",
        help="Research request ID (default: REQ-20251104-A3DFF566)",
    )

    args = parser.parse_args()

    success = await create_delivery_approval(args.request_id)

    if success:
        print("✓ Approval created successfully")
        sys.exit(0)
    else:
        print("✗ Failed to create approval")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
