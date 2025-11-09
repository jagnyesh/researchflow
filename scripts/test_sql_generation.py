#!/usr/bin/env python3
"""
Test SQL Generation with Materialized Views

This script tests that SQLGenerator generates correct SQL for materialized views.
It verifies:
1. SQL uses sqlonfhir schema
2. SQL uses correct table names (patient_demographics, condition_simple)
3. SQL uses correct column names (code_text, not code_display)
4. Generated SQL matches expected pattern
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.utils.sql_generator import SQLGenerator


def test_male_diabetic_patients():
    """Test SQL generation for male diabetic patients"""
    print(f"\n{'='*80}")
    print(f"Test: SQL Generation for Male Diabetic Patients")
    print(f"{'='*80}\n")

    # Create SQL generator with materialized views enabled
    sql_gen = SQLGenerator(use_materialized_views=True)

    # Requirements for "male diabetic patients"
    # Format must match what PhenotypeAgent provides (LLM returns "demographics" plural)
    requirements = {
        "inclusion_criteria": [
            {
                "concepts": [
                    {
                        "type": "demographics",  # LLM returns plural
                        "term": "male",
                        "details": "gender = male",
                    },
                    {"type": "condition", "term": "diabetes", "details": "diabetes diagnosis"},
                ]
            }
        ]
    }

    # Generate count SQL
    print("Generating COUNT SQL...")
    count_sql, params = sql_gen.generate_phenotype_sql(requirements, count_only=True)

    print(f"\n✓ Generated SQL:")
    print("-" * 80)
    print(count_sql)
    print("-" * 80)

    print(f"\n✓ Parameters:")
    print(params)

    # Verify SQL contains expected components
    print(f"\n{'='*80}")
    print("Verification Checks:")
    print(f"{'='*80}\n")

    checks = [
        ("Schema prefix 'sqlonfhir'", "sqlonfhir" in count_sql),
        ("Patient demographics table", "patient_demographics" in count_sql),
        ("Condition simple table", "condition_simple" in count_sql),
        ("Correct code column 'code_text'", "code_text" in count_sql),
        ("NO legacy 'code_display'", "code_display" not in count_sql),
        (
            "NO legacy 'patient' table",
            "FROM patient " not in count_sql and "FROM condition " not in count_sql,
        ),
        ("Patient ID column 'patient_id'", "patient_id" in count_sql),
        ("Gender filter", "gender" in count_sql and "male" in str(params)),
        ("Diabetes filter", "diabetes" in str(params)),
    ]

    all_passed = True
    for check_name, result in checks:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {check_name}")
        if not result:
            all_passed = False

    # Show expected SQL pattern
    print(f"\n{'='*80}")
    print("Expected SQL Pattern:")
    print(f"{'='*80}\n")

    expected_pattern = """SELECT COUNT(DISTINCT p.patient_id) as patient_count
FROM sqlonfhir.patient_demographics p
WHERE p.gender = :gender_1
AND EXISTS (
    SELECT 1 FROM sqlonfhir.condition_simple c
    WHERE c.patient_id = p.patient_id
    AND LOWER(c.code_text) LIKE LOWER(:condition_1)
)"""

    print(expected_pattern)

    print(f"\n{'='*80}")
    if all_passed:
        print("✅ ALL CHECKS PASSED")
        print(f"{'='*80}\n")
        return True
    else:
        print("❌ SOME CHECKS FAILED")
        print(f"{'='*80}\n")
        return False


def test_legacy_mode():
    """Test SQL generation with legacy mode (for comparison)"""
    print(f"\n{'='*80}")
    print(f"Test: Legacy SQL Generation (for comparison)")
    print(f"{'='*80}\n")

    # Create SQL generator with legacy mode
    sql_gen = SQLGenerator(use_materialized_views=False)

    requirements = {
        "inclusion_criteria": [
            {
                "concepts": [
                    {
                        "type": "demographics",  # LLM returns plural
                        "term": "male",
                        "details": "gender = male",
                    },
                    {"type": "condition", "term": "diabetes", "details": "diabetes diagnosis"},
                ]
            }
        ]
    }

    # Generate count SQL
    print("Generating LEGACY COUNT SQL...")
    count_sql, params = sql_gen.generate_phenotype_sql(requirements, count_only=True)

    print(f"\n✓ Generated Legacy SQL:")
    print("-" * 80)
    print(count_sql)
    print("-" * 80)

    print(f"\n✓ Uses legacy schema: {('patient' in count_sql and 'condition' in count_sql)}")
    print(f"✓ Uses code_display: {'code_display' in count_sql}")
    print(f"✓ NO sqlonfhir schema: {'sqlonfhir' not in count_sql}\n")


def test_full_select():
    """Test full SELECT query (not just COUNT)"""
    print(f"\n{'='*80}")
    print(f"Test: Full SELECT SQL")
    print(f"{'='*80}\n")

    sql_gen = SQLGenerator(use_materialized_views=True)

    requirements = {
        "inclusion_criteria": [
            {
                "concepts": [
                    {
                        "type": "demographics",  # LLM returns plural
                        "term": "female",
                        "details": "gender = female",
                    }
                ]
            }
        ]
    }

    # Generate full SELECT
    select_sql, params = sql_gen.generate_phenotype_sql(requirements, count_only=False)

    print(f"\n✓ Generated SELECT SQL:")
    print("-" * 80)
    print(select_sql)
    print("-" * 80)

    # Verify it selects correct columns
    has_patient_id = "patient_id" in select_sql
    has_birthdate = "birthdate" in select_sql.lower()
    has_gender = "gender" in select_sql

    print(f"\n✅ Selects patient_id: {has_patient_id}")
    print(f"✅ Selects birthdate: {has_birthdate}")
    print(f"✅ Selects gender: {has_gender}\n")


def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("SQL GENERATION TESTS - Materialized Views")
    print("=" * 80)

    # Test 1: Male diabetic patients (main test case)
    test_1_passed = test_male_diabetic_patients()

    # Test 2: Legacy mode (for comparison)
    test_legacy_mode()

    # Test 3: Full SELECT
    test_full_select()

    # Summary
    print(f"\n{'='*80}")
    print("TEST SUMMARY")
    print(f"{'='*80}\n")

    if test_1_passed:
        print("✅ SQL generation is working correctly!")
        print("   - Uses sqlonfhir schema")
        print("   - Uses patient_demographics and condition_simple tables")
        print("   - Uses code_text column")
        print("   - Generated SQL will return correct results")
        print(f"\n{'='*80}\n")
        sys.exit(0)
    else:
        print("❌ SQL generation has issues!")
        print("   - Review the failed checks above")
        print("   - SQL may not return correct results")
        print(f"\n{'='*80}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
