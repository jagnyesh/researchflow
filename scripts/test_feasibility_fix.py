#!/usr/bin/env python3
"""
Test Feasibility Fix - Submit request and check if estimated_cohort = 28

This script tests the fix for parameterized query execution.
"""

import sys
import os
import asyncio
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.orchestrator import ResearchRequestOrchestrator
from app.agents import (
    RequirementsAgent,
    PhenotypeValidationAgent,
    CalendarAgent,
    DataExtractionAgent,
    QualityAssuranceAgent,
    DeliveryAgent,
)
from app.database import get_db_session
from sqlalchemy import select, text

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_feasibility_fix():
    """
    Submit a test request for male diabetic patients and verify cohort count
    """
    print("\n" + "=" * 80)
    print("TEST: Feasibility Fix - Male Diabetic Patients")
    print("=" * 80 + "\n")

    # Initialize orchestrator
    orchestrator = ResearchRequestOrchestrator()

    # Initialize agents
    hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")

    orchestrator.register_agent("requirements_agent", RequirementsAgent())
    orchestrator.register_agent(
        "phenotype_agent", PhenotypeValidationAgent(database_url=hapi_db_url)
    )
    orchestrator.register_agent("calendar_agent", CalendarAgent())
    orchestrator.register_agent("extraction_agent", DataExtractionAgent())
    orchestrator.register_agent("qa_agent", QualityAssuranceAgent())
    orchestrator.register_agent("delivery_agent", DeliveryAgent())

    # Create test request
    print("📝 Creating test request...")
    request_data = {
        "researcher_name": "Test User",
        "researcher_email": "test@test.com",
        "irb_number": "IRB-TEST-001",
        "initial_request": "I need demographics (family name, given name, date of birth) for male patients with diabetes diagnosis.",
        "structured_requirements": {
            "study_title": "Male Diabetic Patients Test",
            "principal_investigator": "Test User",
            "irb_number": "IRB-TEST-001",
            "inclusion_criteria": [
                {
                    "description": "Male patients",
                    "concepts": [
                        {"term": "male", "type": "demographics", "details": "male gender"}
                    ],
                },
                {
                    "description": "Diabetes diagnosis",
                    "concepts": [
                        {
                            "term": "diabetes",
                            "type": "condition",
                            "details": "any diabetes diagnosis",
                        }
                    ],
                },
            ],
            "exclusion_criteria": [],
            "data_elements": ["Family name", "Given name", "Date of birth"],
            "time_period": {"start": None, "end": None},
            "phi_level": "identified",
            "delivery_format": "CSV",
        },
    }

    request_id = await orchestrator.submit_request(request_data)
    print(f"✅ Request created: {request_id}\n")

    # Wait for phenotype validation to complete
    print("⏳ Waiting for phenotype validation (max 30 seconds)...")
    await asyncio.sleep(30)

    # Check the results
    print("\n" + "-" * 80)
    print("Checking Results in Database")
    print("-" * 80 + "\n")

    async with get_db_session() as session:
        # Get approval data
        result = await session.execute(
            text(
                """
                SELECT
                    approval_data::json->'estimated_cohort' as estimated_cohort,
                    approval_data::json->'feasibility_score' as feasibility_score,
                    approval_data::json->'auto_feasibility_assessment' as assessment,
                    approval_data::json->'sql_query' as sql_query
                FROM approvals
                WHERE request_id = :request_id
                  AND approval_type = 'phenotype_sql'
                ORDER BY submitted_at DESC
                LIMIT 1
            """
            ),
            {"request_id": request_id},
        )

        approval_row = result.fetchone()

        if approval_row:
            estimated_cohort = approval_row[0]
            feasibility_score = approval_row[1]
            assessment = approval_row[2]
            sql_query = approval_row[3]

            print(f"📊 Estimated Cohort: {estimated_cohort}")
            print(f"📈 Feasibility Score: {feasibility_score}")
            print(f"✓ Assessment: {assessment}")
            print(f"\n📝 Generated SQL (first 200 chars):")
            print(f"{str(sql_query)[:200]}...")

            # Check if fix worked
            print("\n" + "=" * 80)
            if estimated_cohort == 28 or estimated_cohort == "28":
                print("✅ SUCCESS! Fix worked - estimated_cohort = 28")
                print("=" * 80 + "\n")
                return True
            elif estimated_cohort == 0 or estimated_cohort == "0":
                print("❌ FAILED! Still getting 0 patients")
                print("   Issue persists - need to investigate further")
                print("=" * 80 + "\n")
                return False
            else:
                print(f"⚠️  Got {estimated_cohort} patients (expected 28)")
                print("   Close, but may need adjustment")
                print("=" * 80 + "\n")
                return False
        else:
            print("❌ No approval found - phenotype validation may not have completed")
            print("=" * 80 + "\n")
            return False


async def main():
    try:
        success = await test_feasibility_fix()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
