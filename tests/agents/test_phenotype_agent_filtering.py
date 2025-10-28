#!/usr/bin/env python3
"""
Test Phenotype Agent Filtering

Tests the improved _estimate_cohort_size method that filters by requirements.

Expected results with HAPI database:
- All patients: 105
- Female patients: ~46
- Female patients aged 20-30: ~7
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from app.agents.phenotype_agent import PhenotypeValidationAgent


async def test_phenotype_filtering():
    """Test phenotype agent with gender + age filtering"""

    print("=" * 80)
    print("Test: Phenotype Agent Filtering")
    print("=" * 80)
    print()

    # Initialize agent with HAPI database
    # Use SQLite for legacy adapter (not used), but pass HAPI URL for ViewDefinitions
    hapi_url = "postgresql://hapi:hapi@localhost:5433/hapi"
    agent = PhenotypeValidationAgent(database_url="sqlite+aiosqlite:///./dev.db")

    # Manually set up HAPI database for ViewDefinitions
    from app.clients.hapi_db_client import HAPIDBClient
    from app.sql_on_fhir.runner.postgres_runner import PostgresRunner

    agent.use_view_definitions = True
    agent.hapi_db_client = HAPIDBClient(connection_url=hapi_url)
    agent.postgres_runner = PostgresRunner(
        db_client=agent.hapi_db_client,
        enable_cache=False
    )

    # Wait for database connection
    if agent.hapi_db_client and not agent.hapi_db_client.pool:
        print("Connecting to HAPI database...")
        await agent.hapi_db_client.connect()
        print("✓ Connected\n")

    try:
        # Test 1: All patients (no requirements)
        print("Test 1: All patients (no requirements)")
        print("-" * 80)

        count1 = await agent._estimate_cohort_size(count_sql="", requirements=None)
        print(f"Result: {count1} patients\n")

        # Test 2: Female patients only
        print("Test 2: Female patients only")
        print("-" * 80)

        requirements2 = {
            "inclusion_criteria": [
                {
                    "text": "female patients",
                    "concepts": [
                        {
                            "term": "female",
                            "type": "demographic",
                            "details": "female patients"
                        }
                    ]
                }
            ],
            "exclusion_criteria": [],
            "data_elements": [],
            "time_period": {},
            "phi_level": "de-identified"
        }

        count2 = await agent._estimate_cohort_size(count_sql="", requirements=requirements2)
        print(f"Result: {count2} female patients\n")

        # Test 3: Female patients aged 20-30
        print("Test 3: Female patients aged 20-30")
        print("-" * 80)

        requirements3 = {
            "inclusion_criteria": [
                {
                    "text": "female patients",
                    "concepts": [
                        {
                            "term": "female",
                            "type": "demographic",
                            "details": "female patients"
                        }
                    ]
                },
                {
                    "text": "age between 20 and 30",
                    "concepts": [
                        {
                            "term": "age",
                            "type": "demographic",
                            "details": "between 20 and 30"
                        }
                    ]
                }
            ],
            "exclusion_criteria": [],
            "data_elements": [],
            "time_period": {},
            "phi_level": "de-identified"
        }

        count3 = await agent._estimate_cohort_size(count_sql="", requirements=requirements3)
        print(f"Result: {count3} female patients aged 20-30\n")

        # Summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"All patients:               {count1}")
        print(f"Female patients:            {count2}")
        print(f"Female patients aged 20-30: {count3}")
        print()

        # Validation
        print("=" * 80)
        print("VALIDATION")
        print("=" * 80)

        if count1 > 0:
            print("✅ Test 1 PASSED: Found patients in database")
        else:
            print("❌ Test 1 FAILED: No patients found")

        if count2 > 0 and count2 < count1:
            print("✅ Test 2 PASSED: Gender filtering works")
        else:
            print(f"❌ Test 2 FAILED: Gender filter not working (count2={count2}, count1={count1})")

        if count3 > 0 and count3 < count2:
            print("✅ Test 3 PASSED: Age filtering works")
        else:
            print(f"❌ Test 3 FAILED: Age filter not working (count3={count3}, count2={count2})")

        print()

        # Expected values based on test_viewdef_approach.py results
        print("Expected values (from previous test):")
        print("  - Female patients: ~46")
        print("  - Female patients aged 20-30: ~7")
        print()

    finally:
        # Cleanup
        if agent.hapi_db_client:
            await agent.hapi_db_client.close()
            print("✓ Database connection closed")


if __name__ == "__main__":
    asyncio.run(test_phenotype_filtering())
