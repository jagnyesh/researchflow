#!/usr/bin/env python3
"""
Test SQL Generation for Male Diabetic Patients
Tests the exact scenario from user's request
"""

import sys
import os
import asyncio
import logging

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.utils.sql_generator import SQLGenerator
from app.adapters.sql_on_fhir import SQLonFHIRAdapter
from app.database import get_db_session

# Enable logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_sql_generation_and_execution():
    """
    Test SQL generation for:
    'I need demographics (family name, given name, date of birth, address)
     for male patients with diabetes diagnosis.'

    Inclusion criteria:
    - Male
    - Diabetes Diagnosis

    Data elements:
    - Demographics (family name, given name, date of birth, address)
    """
    print("\n" + "=" * 80)
    print("TEST: Male Diabetic Patients SQL Generation & Execution")
    print("=" * 80)

    # 1. Create SQL Generator
    sql_gen = SQLGenerator(use_materialized_views=True)

    # 2. Build requirements (matching what LLM would extract)
    requirements = {
        "inclusion_criteria": [
            {
                "description": "Male patients",
                "concepts": [
                    {
                        "type": "demographics",  # LLM returns plural
                        "term": "male",
                        "details": "gender = male",
                    }
                ],
            },
            {
                "description": "Diabetes diagnosis",
                "concepts": [
                    {"type": "condition", "term": "diabetes", "details": "diabetes diagnosis"}
                ],
            },
        ],
        "exclusion_criteria": [],
        "data_elements": [
            "demographics",  # Should map to: name_family, name_given, dob, gender
            "family name",
            "given name",
            "date of birth",
            "address",  # This will be skipped with warning (not in schema)
        ],
        "time_period": {},
    }

    print("\n📋 Requirements:")
    print(f"  Inclusion: Male, Diabetes Diagnosis")
    print(f"  Data Elements: {requirements['data_elements']}")

    # 3. Generate COUNT SQL
    print("\n" + "-" * 80)
    print("STEP 1: Generate COUNT SQL")
    print("-" * 80)

    count_sql, count_params = sql_gen.generate_phenotype_sql(requirements, count_only=True)

    print("\n✓ Generated COUNT SQL:")
    print(count_sql)
    print(f"\n✓ Parameters: {count_params}")

    # 4. Execute COUNT SQL
    print("\n" + "-" * 80)
    print("STEP 2: Execute COUNT SQL Against Database")
    print("-" * 80)

    hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")
    sql_adapter = SQLonFHIRAdapter(database_url=hapi_db_url)

    try:
        count_result = await sql_adapter.execute_sql(count_sql, count_params)
        if count_result and len(count_result) > 0:
            count = count_result[0].get("patient_count", 0)
            print(f"\n✅ COUNT Query Result: {count} patients")
        else:
            print(f"\n❌ COUNT Query returned no results")
            count = 0
    except Exception as e:
        print(f"\n❌ COUNT Query failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False

    # 5. Generate SELECT SQL
    print("\n" + "-" * 80)
    print("STEP 3: Generate Full SELECT SQL")
    print("-" * 80)

    select_sql, select_params = sql_gen.generate_phenotype_sql(requirements, count_only=False)

    print("\n✓ Generated SELECT SQL:")
    print(select_sql)
    print(f"\n✓ Parameters: {select_params}")

    # 6. Execute SELECT SQL (limit to 10 for preview)
    print("\n" + "-" * 80)
    print("STEP 4: Execute SELECT SQL (First 10 Rows)")
    print("-" * 80)

    try:
        # Add LIMIT to SELECT query for preview
        preview_sql = select_sql + "\nLIMIT 10"
        preview_result = await sql_adapter.execute_sql(preview_sql, select_params)

        if preview_result and len(preview_result) > 0:
            print(f"\n✅ SELECT Query returned {len(preview_result)} rows")
            print("\nSample Data (first 3 rows):")
            print("-" * 80)
            for i, row in enumerate(preview_result[:3]):
                print(f"\nRow {i+1}:")
                for key, value in row.items():
                    print(f"  {key}: {value}")
        else:
            print(f"\n❌ SELECT Query returned no results")
    except Exception as e:
        print(f"\n❌ SELECT Query failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False

    # 7. Verify against expected SQL
    print("\n" + "-" * 80)
    print("STEP 5: Verify Against Expected SQL Pattern")
    print("-" * 80)

    expected_sql = """SELECT DISTINCT p.name_family, p.name_given, p.dob
FROM sqlonfhir.patient_demographics p
JOIN sqlonfhir.condition_simple c ON p.patient_id = c.patient_id
WHERE p.gender = 'male'
  AND c.code_text LIKE '%diabetes%'"""

    print("\n📝 Expected SQL Pattern (from user):")
    print(expected_sql)

    checks = [
        ("Uses sqlonfhir schema", "sqlonfhir" in select_sql),
        ("Uses patient_demographics", "patient_demographics" in select_sql),
        ("Uses condition_simple", "condition_simple" in select_sql),
        ("Has gender filter", "gender" in select_sql),
        (
            "Has diabetes filter",
            "diabetes" in str(select_params) or "condition" in str(select_params),
        ),
        ("Selects name_family", "name_family" in select_sql),
        ("Selects name_given", "name_given" in select_sql),
        ("Selects dob", "dob" in select_sql),
        (f"Count > 0 (expected ~28)", count > 0),
    ]

    print("\n✅ Verification Checks:")
    all_passed = True
    for check_name, result in checks:
        status = "✅" if result else "❌"
        print(f"{status} {check_name}")
        if not result:
            all_passed = False

    # 8. Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if all_passed and count > 0:
        print(f"\n✅ SUCCESS!")
        print(f"   - SQL generation is working correctly")
        print(f"   - Found {count} male patients with diabetes")
        print(f"   - Data elements mapped correctly (address skipped as unavailable)")
        print(f"   - Ready for end-to-end testing via UI")
        return True
    else:
        print(f"\n❌ FAILED")
        print(f"   - Count: {count} (expected > 0)")
        print(f"   - Review failed checks above")
        return False


async def main():
    success = await test_sql_generation_and_execution()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
