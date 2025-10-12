"""
Simple Query Test - Prove End-to-End System Works

Tests with a simplified ViewDefinition to verify the core system executes successfully.
"""

import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.clients.hapi_db_client import create_hapi_db_client, close_hapi_db_client
from app.sql_on_fhir.transpiler import (
    create_fhirpath_transpiler,
    create_column_extractor
)
from app.sql_on_fhir.query_builder import create_sql_query_builder
from dotenv import load_dotenv

load_dotenv()


def load_view_definition(name: str) -> dict:
    """Load ViewDefinition from JSON file"""
    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'app', 'sql_on_fhir', 'view_definitions',
        f'{name}.json'
    )
    with open(path, 'r') as f:
        return json.load(f)


async def main():
    print("=" * 80)
    print("SIMPLE QUERY - END-TO-END TEST")
    print("=" * 80)

    try:
        # Setup
        print("\n✓ Setting up components...")
        client = await create_hapi_db_client()
        transpiler = create_fhirpath_transpiler()
        extractor = create_column_extractor(transpiler)
        builder = create_sql_query_builder(transpiler, extractor)

        # Load simple ViewDefinition
        view_def = load_view_definition('patient_simple')

        print(f"✓ Loaded ViewDefinition: {view_def['name']}")
        print(f"  Resource: {view_def['resource']}")
        print(f"  Columns: {len(view_def['select'][0]['column'])}")

        # Build query
        query = builder.build_query(view_def, limit=10)

        print(f"\n✓ Built SQL query:")
        print(f"  Columns: {query.column_count}")
        print(f"  Has lateral joins: {query.has_lateral_joins}")

        print(f"\n  Generated SQL:")
        print("  " + "-" * 76)
        for line in query.sql.split('\n'):
            print(f"  {line}")
        print("  " + "-" * 76)

        # Execute query
        print(f"\n✓ Executing query against HAPI database...")
        rows = await client.execute_query(query.sql)

        print(f"✓✓✓ SUCCESS! Query executed successfully!")
        print(f"  Returned {len(rows)} patients")

        # Display results
        if rows:
            print(f"\n  Patient Data:")
            print(f"  {'ID':8} {'Active':8} {'Gender':8} {'Birth Date':12}")
            print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*12}")
            for row in rows:
                print(f"  {str(row.get('id', ''))[:8]:8} "
                      f"{str(row.get('active', ''))[:8]:8} "
                      f"{str(row.get('gender', ''))[:8]:8} "
                      f"{str(row.get('birth_date', ''))[:12]:12}")

        # Test with search params
        print(f"\n✓ Testing with search parameters (gender=male)...")
        query_male = builder.build_query(view_def, search_params={'gender': 'male'}, limit=5)

        rows_male = await client.execute_query(query_male.sql)
        print(f"✓ Found {len(rows_male)} male patients")

        # Test COUNT query
        print(f"\n✓ Testing COUNT query...")
        count_sql = builder.build_count_query(view_def)

        count_rows = await client.execute_query(count_sql)
        total = count_rows[0]['count']
        print(f"✓ Total patients in database: {total}")

        # SUCCESS
        print("\n" + "=" * 80)
        print("✓✓✓ ALL TESTS PASSED! ✓✓✓")
        print("=" * 80)
        print("\nThe in-database ViewDefinition runner works!")
        print("We successfully:")
        print("  1. Transpiled FHIRPath to PostgreSQL JSONB queries")
        print("  2. Extracted columns from ViewDefinition")
        print("  3. Built complete SQL SELECT statements")
        print("  4. Executed queries against live HAPI FHIR database")
        print("  5. Retrieved and parsed FHIR resource data")
        print("\nNext: Wrap in PostgresRunner class and integrate with Analytics API")
        print("=" * 80 + "\n")

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await close_hapi_db_client()


if __name__ == "__main__":
    asyncio.run(main())
