#!/usr/bin/env python3
"""
Test SQL Adapter with Parameterized Queries

This script directly tests if the SQL adapter properly handles parameters.
"""

import sys
import os
import asyncio

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.adapters.sql_on_fhir import SQLonFHIRAdapter


async def test_adapter_with_params():
    """Test if SQL adapter executes parameterized queries correctly"""

    print("\n" + "=" * 80)
    print("TEST: SQL Adapter with Parameterized Queries")
    print("=" * 80 + "\n")

    # Initialize adapter (need asyncpg driver for SQLAlchemy async)
    hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")
    # Convert to asyncpg format for SQLAlchemy
    if "postgresql://" in hapi_db_url and "+asyncpg" not in hapi_db_url:
        hapi_db_url = hapi_db_url.replace("postgresql://", "postgresql+asyncpg://")

    adapter = SQLonFHIRAdapter(database_url=hapi_db_url)

    # Test 1: Query WITH parameters (should return 28)
    print("Test 1: Query WITH parameters")
    print("-" * 80)

    sql_with_params = """
SELECT COUNT(DISTINCT p.patient_id) as patient_count
FROM sqlonfhir.patient_demographics p
WHERE p.gender = :gender_1
  AND EXISTS (
    SELECT 1 FROM sqlonfhir.condition_simple c
    WHERE c.patient_id = p.patient_id
    AND LOWER(c.code_text) LIKE LOWER(:condition_2)
  )
"""

    params = {"gender_1": "male", "condition_2": "%diabetes%"}

    print(f"SQL: {sql_with_params.strip()}")
    print(f"Parameters: {params}")

    try:
        result = await adapter.execute_sql(sql_with_params, params)
        count = result[0]["patient_count"] if result else 0
        print(f"\n✓ Result: {count} patients")

        if count == 28:
            print("✅ SUCCESS! Got expected 28 patients with parameters")
        else:
            print(f"❌ FAILED! Expected 28, got {count}")
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback

        traceback.print_exc()

    # Test 2: Query WITHOUT parameters (should fail or return wrong results)
    print("\n\nTest 2: Query WITHOUT parameters (placeholders unbound)")
    print("-" * 80)

    sql_no_params = """
SELECT COUNT(DISTINCT p.patient_id) as patient_count
FROM sqlonfhir.patient_demographics p
WHERE p.gender = :gender_1
  AND EXISTS (
    SELECT 1 FROM sqlonfhir.condition_simple c
    WHERE c.patient_id = p.patient_id
    AND LOWER(c.code_text) LIKE LOWER(:condition_2)
  )
"""

    print(f"SQL: {sql_no_params.strip()}")
    print(f"Parameters: None (or empty dict)")

    try:
        result = await adapter.execute_sql(sql_no_params, None)
        count = result[0]["patient_count"] if result else 0
        print(f"\n✓ Result: {count} patients")
        print("⚠️ This should have failed or returned 0 (unbound parameters)")
    except Exception as e:
        print(f"✓ ERROR (expected): {str(e)}")

    # Test 3: Direct SQL without placeholders (should return 28)
    print("\n\nTest 3: Direct SQL without placeholders")
    print("-" * 80)

    sql_direct = """
SELECT COUNT(DISTINCT p.patient_id) as patient_count
FROM sqlonfhir.patient_demographics p
WHERE p.gender = 'male'
  AND EXISTS (
    SELECT 1 FROM sqlonfhir.condition_simple c
    WHERE c.patient_id = p.patient_id
    AND LOWER(c.code_text) LIKE '%diabetes%'
  )
"""

    print(f"SQL: {sql_direct.strip()}")

    try:
        result = await adapter.execute_sql(sql_direct, None)
        count = result[0]["patient_count"] if result else 0
        print(f"\n✓ Result: {count} patients")

        if count == 28:
            print("✅ SUCCESS! Direct SQL works correctly")
        else:
            print(f"❌ FAILED! Expected 28, got {count}")
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80 + "\n")
    print("If Test 1 returns 28, then parameterized queries work correctly.")
    print("If Test 1 returns 0, there's a bug in how parameters are bound.")
    print("\n")


if __name__ == "__main__":
    asyncio.run(test_adapter_with_params())
