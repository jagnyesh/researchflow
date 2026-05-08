#!/usr/bin/env python3
"""
Verification Script: Female Diabetes Patient Count

This script verifies that the count mismatch issue has been fixed.
It runs both manual SQL queries and ResearchFlow's SQL generation to ensure
they return the same count (19 patients).

Run this script after fixing the issue to verify:
1. Manual query with LOWER() returns 19 patients
2. ResearchFlow SQL generation returns 19 patients
3. Patient 326492 (Schneider199) is included
4. All patients have expected demographics

Usage:
    python scripts/verify_diabetes_count_fix.py
    OR
    HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi python scripts/verify_diabetes_count_fix.py  # pragma: allowlist secret
"""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.sql_generator import SQLGenerator
from app.adapters.sql_on_fhir import SQLonFHIRAdapter


async def verify_manual_query_case_sensitive():
    """
    Test 1: Verify case-sensitive manual query returns 18 patients (WRONG)

    This demonstrates the original bug.
    """
    print("\n" + "=" * 80)
    print("Test 1: Manual Query (Case-Sensitive) - SHOULD FAIL")
    print("=" * 80)

    adapter = SQLonFHIRAdapter()

    # Original manual query (case-sensitive LIKE)
    manual_sql = """
        SELECT COUNT(DISTINCT pd.patient_id) as patient_count
        FROM sqlonfhir.patient_demographics pd
        INNER JOIN sqlonfhir.condition_simple cs ON pd.patient_id = cs.patient_id
        WHERE pd.gender = :gender AND cs.icd10_display LIKE :condition
    """

    params = {"gender": "female", "condition": "%diabetes%"}

    try:
        result = await adapter.execute_sql(manual_sql, params)
        count = result[0]["patient_count"] if result else 0

        print(f"✗ Case-sensitive LIKE: {count} patients (INCORRECT - misses Schneider199)")
        print("  This is the ORIGINAL BUG - missing patient with capital-D 'Diabetes'")

        return count == 18  # Should be 18 (the bug)

    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return False


async def verify_manual_query_case_insensitive():
    """
    Test 2: Verify case-insensitive manual query returns 19 patients (CORRECT)

    This demonstrates the fix for manual queries.
    """
    print("\n" + "=" * 80)
    print("Test 2: Manual Query (Case-Insensitive) - SHOULD PASS")
    print("=" * 80)

    adapter = SQLonFHIRAdapter()

    # Fixed manual query (case-insensitive LOWER)
    manual_sql_fixed = """
        SELECT COUNT(DISTINCT pd.patient_id) as patient_count
        FROM sqlonfhir.patient_demographics pd
        INNER JOIN sqlonfhir.condition_simple cs ON pd.patient_id = cs.patient_id
        WHERE pd.gender = :gender AND LOWER(cs.icd10_display) LIKE LOWER(:condition)
    """

    params = {"gender": "female", "condition": "%diabetes%"}

    try:
        result = await adapter.execute_sql(manual_sql_fixed, params)
        count = result[0]["patient_count"] if result else 0

        if count == 19:
            print(f"✓ Case-insensitive LOWER(): {count} patients (CORRECT)")
        else:
            print(f"✗ Case-insensitive LOWER(): {count} patients (EXPECTED 19)")

        return count == 19

    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return False


async def verify_researchflow_sql_generation():
    """
    Test 3: Verify ResearchFlow SQL generation returns 19 patients (CORRECT)

    This verifies that sql_generator.py uses LOWER() correctly.
    """
    print("\n" + "=" * 80)
    print("Test 3: ResearchFlow SQL Generation - SHOULD PASS")
    print("=" * 80)

    adapter = SQLonFHIRAdapter()
    generator = SQLGenerator(use_materialized_views=True)

    # Generate SQL using ResearchFlow's sql_generator
    requirements = {
        "inclusion_criteria": [{"type": "condition", "details": "diabetes"}],
        "exclusion_criteria": [],
        "data_elements": ["demographics"],
        "demographics": {"gender": "female"},
    }

    count_sql, count_params = generator.generate_phenotype_sql(requirements, count_only=True)

    # Verify LOWER() is used
    if "LOWER(c.icd10_display) LIKE LOWER(" not in count_sql:
        print("✗ SQL does NOT use LOWER() - case-sensitive matching detected!")
        print(f"Generated SQL:\n{count_sql}")
        return False

    print("✓ Generated SQL uses LOWER() for case-insensitive matching")

    # Verify icd10_display column is used (not code_text)
    if "icd10_display" not in count_sql:
        print("⚠ Warning: SQL uses code_text instead of icd10_display (works but less semantic)")

    # Execute query
    try:
        result = await adapter.execute_sql(count_sql, count_params)
        count = result[0]["patient_count"] if result else 0

        if count == 19:
            print(f"✓ ResearchFlow query: {count} patients (CORRECT)")
        else:
            print(f"✗ ResearchFlow query: {count} patients (EXPECTED 19)")

        print(f"\nGenerated SQL:\n{count_sql}")
        print(f"\nParameters: {count_params}")

        return count == 19

    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return False


async def verify_schneider199_included():
    """
    Test 4: Verify patient 326492 (Schneider199) is included in results

    This patient has "Diabetes mellitus type 2" (capital D) and should be found.
    """
    print("\n" + "=" * 80)
    print("Test 4: Verify Schneider199 (Patient 326492) is Included - SHOULD PASS")
    print("=" * 80)

    adapter = SQLonFHIRAdapter()
    generator = SQLGenerator(use_materialized_views=True)

    # Generate extraction SQL (not just count)
    requirements = {
        "inclusion_criteria": [{"type": "condition", "details": "diabetes"}],
        "exclusion_criteria": [],
        "data_elements": ["demographics"],
        "demographics": {"gender": "female"},
    }

    extraction_sql, extraction_params = generator.generate_phenotype_sql(
        requirements, count_only=False
    )

    try:
        results = await adapter.execute_sql(extraction_sql, extraction_params)

        # Check if Schneider199 is in results
        schneider_found = False
        for row in results:
            if row.get("patient_id") == "326492" or row.get("name_family") == "Schneider199":
                schneider_found = True
                print(f"✓ Patient 326492 (Schneider199) FOUND in results")
                print(f"  Details: {row}")
                break

        if not schneider_found:
            print(f"✗ Patient 326492 (Schneider199) NOT FOUND - case sensitivity issue!")
            print(f"  Total patients returned: {len(results)}")
            return False

        return True

    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return False


async def verify_demographics_data_quality():
    """
    Test 5: Check data quality - NULL given_name issue

    Separate from count issue, but worth documenting.
    """
    print("\n" + "=" * 80)
    print("Test 5: Data Quality Check (NULL given_name) - INFORMATIONAL")
    print("=" * 80)

    adapter = SQLonFHIRAdapter()

    sql = """
        SELECT
            COUNT(*) as total_patients,
            COUNT(pd.name_given) as patients_with_given_name,
            COUNT(*) - COUNT(pd.name_given) as patients_missing_given_name
        FROM sqlonfhir.patient_demographics pd
        INNER JOIN sqlonfhir.condition_simple cs ON pd.patient_id = cs.patient_id
        WHERE pd.gender = :gender AND LOWER(cs.icd10_display) LIKE LOWER(:condition)
    """

    params = {"gender": "female", "condition": "%diabetes%"}

    try:
        result = await adapter.execute_sql(sql, params)
        if result:
            total = result[0]["total_patients"]
            with_given = result[0]["patients_with_given_name"]
            missing_given = result[0]["patients_missing_given_name"]

            print(f"Total female diabetes patients: {total}")
            print(f"Patients with given_name: {with_given}")
            print(f"Patients with NULL given_name: {missing_given}")

            if missing_given > 0:
                print(
                    f"⚠ Warning: {missing_given}/{total} patients have NULL given_name (data quality issue)"
                )
            else:
                print("✓ All patients have given_name")

        return True

    except Exception as e:
        print(f"✗ Error: {str(e)}")
        return False


async def main():
    """Run all verification tests"""
    print("\n" + "=" * 80)
    print("VERIFICATION: Female Diabetes Patient Count Fix")
    print("=" * 80)
    print("\nIssue: Count mismatch due to case-sensitive LIKE matching")
    print("Expected: 19 female patients with diabetes (including Schneider199)")
    print("Root Cause: 'Diabetes' (capital D) doesn't match '%diabetes%' case-sensitively")
    print("Fix: Use LOWER() for case-insensitive matching")
    print("\nSee: docs/ROOT_CAUSE_ANALYSIS_COUNT_MISMATCH.md")

    # Run all tests
    test_results = []

    test_results.append(
        ("Case-Sensitive Manual Query (Bug Demo)", await verify_manual_query_case_sensitive())
    )
    test_results.append(
        ("Case-Insensitive Manual Query (Fixed)", await verify_manual_query_case_insensitive())
    )
    test_results.append(("ResearchFlow SQL Generation", await verify_researchflow_sql_generation()))
    test_results.append(("Schneider199 Included", await verify_schneider199_included()))
    test_results.append(("Data Quality Check", await verify_demographics_data_quality()))

    # Print summary
    print("\n" + "=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)

    all_passed = True
    for test_name, passed in test_results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")
        if not passed and test_name != "Case-Sensitive Manual Query (Bug Demo)":
            all_passed = False

    print("=" * 80)

    if all_passed:
        print("\n✓✓✓ ALL CRITICAL TESTS PASSED ✓✓✓")
        print("\nThe count mismatch issue has been FIXED:")
        print("  - ResearchFlow correctly returns 19 female diabetes patients")
        print("  - Patient 326492 (Schneider199) is included")
        print("  - LOWER() is used for case-insensitive matching")
        return 0
    else:
        print("\n✗✗✗ SOME TESTS FAILED ✗✗✗")
        print("\nPlease review the failures above and ensure:")
        print("  1. Database is running (HAPI FHIR on localhost:5433)")
        print("  2. Materialized views exist (run scripts/materialize_views.py)")
        print("  3. sql_generator.py uses LOWER() and icd10_display")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
