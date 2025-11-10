#!/usr/bin/env python3
"""
Quick test to verify phenotype agent returns correct estimates
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

from app.agents.phenotype_agent import PhenotypeValidationAgent


async def test_female_diabetes():
    """Test female diabetes request"""
    print("\n" + "=" * 80)
    print("Testing Phenotype Agent - Female Diabetes Request")
    print("=" * 80)

    # Get database URL
    hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")

    # Convert to asyncpg format
    if "postgresql://" in hapi_db_url and "+asyncpg" not in hapi_db_url:
        hapi_db_url = hapi_db_url.replace("postgresql://", "postgresql+asyncpg://")

    print(f"\nDatabase URL: {hapi_db_url}")

    # Create phenotype agent
    agent = PhenotypeValidationAgent(database_url=hapi_db_url)

    # Create requirements (mimicking what UI sends)
    context = {
        "requirements": {
            "inclusion_criteria": [
                {
                    "type": "condition",
                    "details": "diabetes",
                    "concepts": [{"type": "condition", "term": "diabetes"}],
                },
                {
                    "type": "demographics",
                    "details": "Female",
                    "concepts": [{"type": "demographics", "term": "gender", "details": "Female"}],
                },
            ],
            "exclusion_criteria": [],
            "data_elements": ["demographics"],
            "demographics": {"gender": "female"},
            "time_period": {},
        },
        "request_id": "TEST-001",
    }

    print("\nExecuting validate_feasibility task...")
    result = await agent.execute_task("validate_feasibility", context)

    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)

    print(f"\nFeasibility: {result.get('feasible')}")
    print(f"Estimated Cohort Size: {result.get('estimated_cohort_size', 'N/A')}")
    print(f"Feasibility Score: {result.get('feasibility_score', 'N/A')}")
    print(f"Data Availability: {result.get('data_availability', 'N/A')}")

    if result.get("sql_generated"):
        print(f"\nGenerated SQL (first 500 chars):\n{result['sql_generated'][:500]}")

        # Check which column is used
        if "icd10_display" in result["sql_generated"]:
            print("\n✓ Using icd10_display column (CORRECT)")
        elif "code_text" in result["sql_generated"]:
            print("\n⚠ Using code_text column (works but less semantic)")

        # Check if LOWER() is used
        if "LOWER(" in result["sql_generated"]:
            print("✓ Using LOWER() for case-insensitive matching (CORRECT)")
        else:
            print("✗ NOT using LOWER() - will miss patients! (BUG)")

    # Verify expected count
    estimated_count = result.get("estimated_cohort_size", 0)

    # Note: Conservative 0.7x factor is applied, so 19 × 0.7 = 13.3 → 13
    expected_conservative = 13

    print("\n" + "=" * 80)
    print("VALIDATION")
    print("=" * 80)

    if estimated_count == expected_conservative:
        print(
            f"✓ PASS: Estimated count ({estimated_count}) matches expected conservative estimate ({expected_conservative})"
        )
        print("  (19 patients × 0.7 conservative factor = 13.3 → 13)")
        return True
    elif estimated_count == 19:
        print(
            f"⚠ WARNING: Estimated count ({estimated_count}) is raw count without conservative factor"
        )
        print("  Expected 13 with 0.7x factor applied")
        return False
    elif estimated_count == 0:
        print(f"✗ FAIL: Estimated count is 0 (query failed or no results)")
        return False
    else:
        print(
            f"✗ FAIL: Estimated count ({estimated_count}) doesn't match expected ({expected_conservative})"
        )
        return False


if __name__ == "__main__":
    success = asyncio.run(test_female_diabetes())
    sys.exit(0 if success else 1)
