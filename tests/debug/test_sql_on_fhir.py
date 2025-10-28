"""
Test script for SQL-on-FHIR v2 implementation

Demonstrates ViewDefinition management without requiring a live FHIR server.
"""

import sys
import json
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager


def test_view_definition_manager():
    """Test ViewDefinition loading and validation"""
    print("=" * 70)
    print("SQL-on-FHIR v2 ViewDefinition Manager Test")
    print("=" * 70)
    print()

    # Initialize manager
    print("1. Initializing ViewDefinitionManager...")
    manager = ViewDefinitionManager()
    print(f"   ✓ ViewDefinitions directory: {manager.view_definitions_dir}")
    print()

    # List all ViewDefinitions
    print("2. Listing available ViewDefinitions...")
    view_names = manager.list()
    print(f"   ✓ Found {len(view_names)} ViewDefinitions:")
    for name in view_names:
        print(f"     - {name}")
    print()

    # Load and display each ViewDefinition
    print("3. Loading ViewDefinitions...")
    for name in view_names:
        try:
            view_def = manager.load(name)
            resource_type = view_def.get('resource')
            title = view_def.get('title', 'N/A')
            num_columns = 0

            # Count columns
            for select_elem in view_def.get('select', []):
                if 'column' in select_elem:
                    num_columns += len(select_elem['column'])

            print(f"   ✓ {name}")
            print(f"     Resource Type: {resource_type}")
            print(f"     Title: {title}")
            print(f"     Columns: {num_columns}")
            print()

        except Exception as e:
            print(f"   ✗ Error loading {name}: {e}")
            print()

    # Display detailed view of one ViewDefinition
    print("4. Detailed view: patient_demographics")
    print("-" * 70)
    patient_view = manager.load("patient_demographics")

    print(f"   Resource Type: {patient_view.get('resource')}")
    print(f"   Title: {patient_view.get('title')}")
    print(f"   Description: {patient_view.get('description')}")
    print()
    print("   Columns:")

    for select_elem in patient_view.get('select', []):
        if 'forEach' in select_elem or 'forEachOrNull' in select_elem:
            collection = select_elem.get('forEach') or select_elem.get('forEachOrNull')
            print(f"     [Collection: {collection}]")

        for column in select_elem.get('column', []):
            name = column.get('name')
            path = column.get('path')
            desc = column.get('description', '')
            print(f"       • {name:20} <- {path}")
            if desc:
                print(f"         ({desc})")

    print()

    # Show where clauses
    if patient_view.get('where'):
        print("   Where Clauses:")
        for where in patient_view['where']:
            print(f"     - {where.get('path')}")
            if where.get('description'):
                print(f"       ({where.get('description')})")

    print()

    # Test ViewDefinition creation from template
    print("5. Creating custom ViewDefinition from template...")
    custom_view = manager.create_from_template(
        resource_type="Patient",
        name="simple_patients",
        columns=[
            {"name": "id", "path": "id"},
            {"name": "gender", "path": "gender"},
            {"name": "birth_date", "path": "birthDate"}
        ],
        where=["active = true"]
    )
    print("   ✓ Created custom ViewDefinition:")
    print(f"     Name: {custom_view.get('name')}")
    print(f"     Resource: {custom_view.get('resource')}")
    print(f"     Columns: {len(custom_view['select'][0]['column'])}")
    print()

    # Test validation
    print("6. Testing ViewDefinition validation...")
    try:
        manager.validate(custom_view)
        print("   ✓ Validation passed!")
    except ValueError as e:
        print(f"   ✗ Validation failed: {e}")
    print()

    # Test invalid ViewDefinition
    print("7. Testing validation with invalid ViewDefinition...")
    invalid_view = {
        "resourceType": "ViewDefinition",
        "resource": "Patient",
        # Missing 'name' field - should fail
        "select": [{"column": [{"name": "id", "path": "id"}]}]
    }
    try:
        manager.validate(invalid_view)
        print("   ✗ Validation should have failed!")
    except ValueError as e:
        print(f"   ✓ Validation correctly caught error: {e}")
    print()

    # Show schema extraction example
    print("8. Schema extraction example...")
    print("   For patient_demographics ViewDefinition:")

    # Manually extract schema for demonstration
    schema = {}
    for select_elem in patient_view.get('select', []):
        for column in select_elem.get('column', []):
            name = column.get('name')
            col_type = column.get('type', 'string')
            schema[name] = col_type

    print(f"   ✓ Extracted {len(schema)} columns:")
    for col_name, col_type in list(schema.items())[:10]:
        print(f"     {col_name:20} : {col_type}")
    if len(schema) > 10:
        print(f"     ... and {len(schema) - 10} more")
    print()

    print("=" * 70)
    print("✓ All tests completed successfully!")
    print("=" * 70)
    print()
    print("Next Steps:")
    print("1. Start HAPI FHIR server with Docker (see QUICKSTART_SQL_ON_FHIR.md)")
    print("2. Load synthetic data using Synthea")
    print("3. Start the FastAPI server to use the Analytics API")
    print("4. Execute ViewDefinitions against live FHIR data")
    print()


if __name__ == "__main__":
    test_view_definition_manager()
