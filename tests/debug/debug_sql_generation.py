#!/usr/bin/env python3
"""
Debug SQL generation for ViewDefinitions
"""

import json
import sys
from app.sql_on_fhir.transpiler import create_fhirpath_transpiler, create_column_extractor
from app.sql_on_fhir.query_builder import create_sql_query_builder


def test_viewdef(viewdef_path: str):
    """Test SQL generation for a ViewDefinition"""
    print(f"\n{'='*80}")
    print(f"Testing ViewDefinition: {viewdef_path}")
    print(f"{'='*80}\n")

    # Load ViewDefinition
    with open(viewdef_path) as f:
        view_def = json.load(f)

    # Create components
    transpiler = create_fhirpath_transpiler()
    extractor = create_column_extractor(transpiler)
    builder = create_sql_query_builder(transpiler, extractor)

    # Generate SQL
    try:
        query = builder.build_query(
            view_def,
            search_params={"gender": "female"},
            limit=5
        )

        print("✅ SQL Generation Successful!")
        print(f"Resource: {query.resource_type}")
        print(f"Columns: {query.column_count}")
        print(f"Has LATERAL: {query.has_lateral_joins}")
        print(f"\nGenerated SQL:\n{'-'*80}")
        print(query.sql)
        print(f"{'-'*80}\n")

    except Exception as e:
        print(f"❌ SQL Generation Failed!")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Test patient_demographics
    test_viewdef("app/sql_on_fhir/view_definitions/patient_demographics.json")

    # Test procedure_history
    test_viewdef("app/sql_on_fhir/view_definitions/procedure_history.json")
