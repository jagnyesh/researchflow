"""
Test script for HAPI database connection

Verifies that we can connect to HAPI FHIR's PostgreSQL database
and query basic resource information.
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.clients.hapi_db_client import create_hapi_db_client
from dotenv import load_dotenv

load_dotenv()


async def main():
    print("=" * 60)
    print("HAPI FHIR Database Connection Test")
    print("=" * 60)

    try:
        # Create client
        print("\n1. Creating HAPI DB client...")
        client = await create_hapi_db_client()
        print("✓ Client created")

        # Test connection
        print("\n2. Testing connection...")
        connected = await client.test_connection()
        if connected:
            print("✓ Connection successful")
        else:
            print("✗ Connection failed")
            return

        # Get database stats
        print("\n3. Fetching database statistics...")
        stats = await client.get_database_stats()
        print(f"✓ Total resources: {stats['total_resources']:,}")
        print(f"✓ Database size: {stats['database_size_mb']:.2f} MB")
        print(f"✓ Pool size: {stats['pool_size']} connections")
        print(f"✓ Free connections: {stats['pool_free_connections']}")

        # Get resource types
        print("\n4. Available resource types:")
        resource_types = await client.get_available_resource_types()
        for rt in resource_types[:10]:  # Show first 10
            count = await client.get_resource_count(rt)
            print(f"   - {rt}: {count:,} resources")

        if len(resource_types) > 10:
            print(f"   ... and {len(resource_types) - 10} more types")

        # Test fetching a resource
        print("\n5. Testing resource fetch...")
        if stats['resource_counts']:
            # Get first available resource type
            first_type = list(stats['resource_counts'].keys())[0]
            print(f"   Fetching sample {first_type} resource...")

            # Get resource IDs
            sql = f"""
                SELECT res_id
                FROM hfj_resource
                WHERE res_type = '{first_type}'
                  AND res_deleted_at IS NULL
                LIMIT 1
            """
            rows = await client.execute_query(sql)

            if rows:
                resource_id = rows[0]['res_id']
                resource = await client.get_resource_by_id(first_type, resource_id)
                if resource:
                    print(f"✓ Successfully fetched {first_type}/{resource.get('id')}")
                    print(f"   Resource keys: {list(resource.keys())[:10]}")

        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Clean up
        from app.clients.hapi_db_client import close_hapi_db_client
        await close_hapi_db_client()
        print("\n✓ Connection closed")


if __name__ == "__main__":
    asyncio.run(main())
