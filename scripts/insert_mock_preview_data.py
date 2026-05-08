#!/usr/bin/env python3
"""
Insert mock preview data for testing the preview extraction UI.

This script inserts mock preview data directly into the database
to demonstrate the preview extraction workflow UI.
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import get_db_session
from app.database.models import DataDelivery, ResearchRequest
from sqlalchemy import select


async def insert_mock_preview_data(request_id: str):
    """Insert mock preview data for a request"""

    async with get_db_session() as session:
        # Get the request
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        if not request:
            print(f"❌ Request {request_id} not found")
            return

        print(f"📋 Request: {request_id}")
        print(f"📋 Current state: {request.current_state}\n")

        # Check if DataDelivery record exists
        result = await session.execute(
            select(DataDelivery).where(DataDelivery.request_id == request_id)
        )
        delivery = result.scalar_one_or_none()

        # Create mock preview data (10 rows per element)
        preview_data = {
            "patient_demographics": [
                {
                    "patient_id": f"PAT-{i:04d}",
                    "name": f"Patient {i}",
                    "birth_date": f"1970-01-{i+1:02d}",
                    "gender": "male",
                }
                for i in range(10)
            ],
            "diagnoses": [
                {
                    "patient_id": f"PAT-{i:04d}",
                    "condition": "Diabetes Mellitus Type 2",
                    "onset_date": f"2020-{i+1:02d}-01",
                }
                for i in range(10)
            ],
            "lab_results": [
                {
                    "patient_id": f"PAT-{i:04d}",
                    "test_name": "HbA1c",
                    "value": f"{7.5 + i*0.1:.1f}",
                    "date": f"2024-{i+1:02d}-01",
                }
                for i in range(10)
            ],
        }

        # Create mock preview QA report
        preview_qa_report = {
            "overall_status": "passed",
            "checks": [
                {
                    "check_name": "Data Completeness",
                    "passed": True,
                    "message": "All data elements have 10 rows as expected",
                },
                {
                    "check_name": "No Duplicates",
                    "passed": True,
                    "message": "No duplicate records found in preview",
                },
                {
                    "check_name": "PHI Scrubbing",
                    "passed": True,
                    "message": "No PHI detected in preview data",
                },
            ],
            "execution_time": "0.5s",
            "timestamp": datetime.utcnow().isoformat(),
        }

        if delivery:
            # Update existing delivery record
            print(f"📝 Updating existing DataDelivery record...")
            delivery.preview_data = preview_data
            delivery.preview_qa_report = preview_qa_report
        else:
            # Create new delivery record
            print(f"📝 Creating new DataDelivery record...")
            delivery = DataDelivery(
                request_id=request_id,
                preview_data=preview_data,
                preview_qa_report=preview_qa_report,
                created_at=datetime.utcnow(),
            )
            session.add(delivery)

        await session.commit()

        print(f"✅ Mock preview data inserted!")
        print(f"   Data elements: {list(preview_data.keys())}")
        print(f"   Rows per element: 10")
        print(f"   QA status: {preview_qa_report['overall_status']}\n")

        # Update request state to preview_qa (showing preview is ready)
        print(f"📝 Updating request state to preview_qa...")
        request.current_state = "preview_qa"
        request.current_agent = "qa_agent"
        await session.commit()

        print(f"✅ Request state updated to preview_qa")
        print(f"\n🎉 Preview data is now visible in both UIs!")


async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Insert mock preview data")
    parser.add_argument("request_id", help="Request ID to insert preview data for")

    args = parser.parse_args()

    print("=" * 60)
    print("INSERT MOCK PREVIEW DATA")
    print("=" * 60 + "\n")

    await insert_mock_preview_data(args.request_id)


if __name__ == "__main__":
    asyncio.run(main())
