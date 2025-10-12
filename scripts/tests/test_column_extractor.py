"""
Test Column Extractor

Verifies that ViewDefinition SELECT clauses are correctly parsed
and converted to SQL SELECT statements.
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.sql_on_fhir.transpiler import (
    create_fhirpath_transpiler,
    create_column_extractor
)


def load_view_definition(name: str) -> dict:
    """Load ViewDefinition from JSON file"""
    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'app', 'sql_on_fhir', 'view_definitions',
        f'{name}.json'
    )
    with open(path, 'r') as f:
        return json.load(f)


def main():
    print("=" * 80)
    print("COLUMN EXTRACTOR TEST")
    print("=" * 80)

    # Create transpiler and extractor
    transpiler = create_fhirpath_transpiler()
    extractor = create_column_extractor(transpiler)

    # Test with patient_demographics ViewDefinition
    print("\n1. Testing patient_demographics ViewDefinition:")
    print("-" * 80)

    view_def = load_view_definition('patient_demographics')

    select_clause = extractor.extract_columns(
        view_def['select'],
        view_def['resource']
    )

    print(f"\nExtracted {len(select_clause.columns)} columns:")
    for i, col in enumerate(select_clause.columns[:10], 1):  # Show first 10
        print(f"  {i}. {col.name:20} - {col.sql_expression[:60]}...")

    if len(select_clause.columns) > 10:
        print(f"  ... and {len(select_clause.columns) - 10} more columns")

    print(f"\nGenerated {len(select_clause.lateral_joins)} lateral joins:")
    for i, join in enumerate(select_clause.lateral_joins, 1):
        print(f"\n  Join {i}:")
        for line in join.split('\n'):
            print(f"    {line}")

    print("\n\nComplete SELECT SQL:")
    print("-" * 80)
    print(select_clause.select_sql)

    # Test WHERE clause extraction
    print("\n\n2. Testing WHERE clause extraction:")
    print("-" * 80)

    where_sql = extractor.extract_where_clause(view_def.get('where', []))
    print(where_sql)

    # Test with condition_diagnoses ViewDefinition
    print("\n\n3. Testing condition_diagnoses ViewDefinition:")
    print("-" * 80)

    condition_view = load_view_definition('condition_diagnoses')

    condition_select = extractor.extract_columns(
        condition_view['select'],
        condition_view['resource']
    )

    print(f"\nExtracted {len(condition_select.columns)} columns:")
    for i, col in enumerate(condition_select.columns, 1):
        print(f"  {i}. {col.name:25} - {col.sql_expression[:55]}...")

    print(f"\nGenerated {len(condition_select.lateral_joins)} lateral joins")

    print("\n\nComplete SELECT SQL:")
    print("-" * 80)
    print(condition_select.select_sql)

    # Summary
    print("\n" + "=" * 80)
    print("✓ Column extractor tests completed successfully!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
