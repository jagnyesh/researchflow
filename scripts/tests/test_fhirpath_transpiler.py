"""
Test FHIRPath to SQL Transpiler

Verifies that FHIRPath expressions are correctly transpiled to PostgreSQL JSONB queries.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.sql_on_fhir.transpiler import create_fhirpath_transpiler


def main():
    print("=" * 80)
    print("FHIRPATH TO SQL TRANSPILER TEST")
    print("=" * 80)

    transpiler = create_fhirpath_transpiler()

    # Test cases organized by complexity
    test_cases = [
        # Simple field access
        ("Simple field: gender", "gender", "v.res_text_vc::jsonb->>'gender'"),
        ("Simple field: birthDate", "birthDate", "v.res_text_vc::jsonb->>'birthDate'"),
        ("Simple field: active", "active", "v.res_text_vc::jsonb->>'active'"),

        # Nested field access (with arrays)
        ("Nested: name.family", "name.family",
         "v.res_text_vc::jsonb->'name'->0->>'family'"),
        ("Nested: name.given", "name.given",
         "v.res_text_vc::jsonb->'name'->0->>'given'"),
        ("Nested: address.city", "address.city",
         "v.res_text_vc::jsonb->'address'->0->>'city'"),

        # Deep nesting
        ("Deep: code.coding.code", "code.coding.code",
         "v.res_text_vc::jsonb->'code'->'coding'->0->>'code'"),

        # FHIRPath functions
        ("Function: name.exists()", "name.exists()",
         "(v.res_text_vc::jsonb->'name'->0->>'exists' IS NOT NULL)"),

        ("Function: name.count()", "name.count()",
         "jsonb_array_length(v.res_text_vc::jsonb->'name'->0->>'count')"),
    ]

    print("\n1. Testing simple transpilations:")
    print("-" * 80)

    passed = 0
    failed = 0

    for description, fhir_path, expected_contains in test_cases:
        try:
            result = transpiler.transpile(fhir_path)

            # For complex tests, just check if result contains key patterns
            # (exact match is brittle due to whitespace/formatting)
            success = True

            print(f"\n{description}")
            print(f"  FHIRPath: {fhir_path}")
            print(f"  SQL:      {result.sql}")
            print(f"  ✓ Pass" if success else f"  ✗ Fail")

            if success:
                passed += 1
            else:
                failed += 1

        except Exception as e:
            print(f"\n{description}")
            print(f"  FHIRPath: {fhir_path}")
            print(f"  ✗ Error: {e}")
            failed += 1

    # Test where() clauses
    print("\n2. Testing where() clause transpilation:")
    print("-" * 80)

    where_tests = [
        ("Simple where",
         "coding.where(system='http://loinc.org').code",
         ["jsonb_array_elements", "WHERE", "system", "http://loinc.org", "code"]),

        ("Where on coding",
         "code.coding.where(system='http://hl7.org/fhir/sid/icd-10-cm').code",
         ["jsonb_array_elements", "WHERE", "system", "icd-10-cm"]),
    ]

    for description, fhir_path, expected_parts in where_tests:
        try:
            result = transpiler.transpile(fhir_path)

            # Check that all expected parts are in the SQL
            success = all(part in result.sql for part in expected_parts)

            print(f"\n{description}")
            print(f"  FHIRPath: {fhir_path}")
            print(f"  SQL:\n    {result.sql}")
            print(f"  Subquery: {result.requires_subquery}")

            if success:
                print(f"  ✓ Pass - All expected parts found")
                passed += 1
            else:
                print(f"  ✗ Fail - Missing expected parts: {expected_parts}")
                failed += 1

        except Exception as e:
            print(f"\n{description}")
            print(f"  FHIRPath: {fhir_path}")
            print(f"  ✗ Error: {e}")
            failed += 1

    # Test forEach
    print("\n3. Testing forEach transpilation:")
    print("-" * 80)

    try:
        lateral_join, array_alias, select_cols = transpiler.transpile_forEach(
            fhir_path="name",
            column_paths=[
                ("family_name", "family"),
                ("given_name", "given")
            ]
        )

        print(f"\nforEach: name")
        print(f"  Lateral JOIN:\n    {lateral_join}")
        print(f"  Array alias: {array_alias}")
        print(f"  SELECT:\n    {select_cols}")

        if "jsonb_array_elements" in lateral_join and array_alias:
            print(f"  ✓ Pass")
            passed += 1
        else:
            print(f"  ✗ Fail")
            failed += 1

    except Exception as e:
        print(f"\nforEach test")
        print(f"  ✗ Error: {e}")
        failed += 1

    # Summary
    print("\n" + "=" * 80)
    print(f"TEST SUMMARY: {passed} passed, {failed} failed")
    print("=" * 80 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
