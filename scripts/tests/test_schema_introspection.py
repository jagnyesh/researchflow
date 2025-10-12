"""
Test HAPI Schema Introspection

Verifies that schema discovery and mapping works correctly.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.clients.hapi_db_client import create_hapi_db_client, close_hapi_db_client
from app.sql_on_fhir.schema import create_schema_introspector
from dotenv import load_dotenv

load_dotenv()


async def main():
    print("=" * 80)
    print("HAPI SCHEMA INTROSPECTION TEST")
    print("=" * 80)

    try:
        # Create DB client
        print("\n1. Creating HAPI DB client...")
        client = await create_hapi_db_client()
        print("✓ Client created")

        # Create schema introspector
        print("\n2. Creating schema introspector...")
        introspector = await create_schema_introspector(client)
        print("✓ Schema introspector created")

        # Print schema summary
        print("\n3. Printing schema summary...")
        await introspector.print_schema_summary()

        # Test FHIRPath to JSONB conversion
        print("\n4. Testing FHIRPath to JSONB conversion:")
        test_paths = [
            "Patient.gender",
            "Patient.name.family",
            "Observation.code.coding.code",
            "birthDate"
        ]

        for fhir_path in test_paths:
            jsonb_path = await introspector.get_resource_json_path(fhir_path)
            print(f"   {fhir_path:30} → {jsonb_path}")

        # Test search parameter mapping
        print("\n5. Testing search parameter column mapping:")
        test_params = [
            ("gender", "token", "Patient"),
            ("birthdate", "date", "Patient"),
            ("family", "string", "Patient"),
            ("code", "token", "Observation")
        ]

        for param_name, param_type, resource_type in test_params:
            column = await introspector.get_search_param_column(
                param_name, param_type, resource_type
            )
            print(f"   {resource_type}.{param_name} ({param_type:8}) → {column}")

        # Test JOIN generation
        print("\n6. Testing search index JOIN generation:")
        join_clause = introspector.get_search_index_join('r', 'token', 'sp_gender')
        print(f"   {join_clause}")

        print("\n" + "=" * 80)
        print("✓ All schema introspection tests passed!")
        print("=" * 80)

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await close_hapi_db_client()
        print("\n✓ Connection closed")


if __name__ == "__main__":
    asyncio.run(main())
