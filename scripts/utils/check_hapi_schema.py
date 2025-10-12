"""
Quick script to investigate HAPI FHIR database schema structure
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.clients.hapi_db_client import create_hapi_db_client, close_hapi_db_client
from dotenv import load_dotenv

load_dotenv()


async def main():
    client = await create_hapi_db_client()

    print("=" * 60)
    print("HAPI FHIR Schema Investigation")
    print("=" * 60)

    # Check hfj_res_ver table structure
    print("\n1. hfj_res_ver table columns:")
    sql = """
        SELECT column_name, data_type, character_maximum_length
        FROM information_schema.columns
        WHERE table_name = 'hfj_res_ver'
        ORDER BY ordinal_position
    """
    columns = await client.execute_query(sql)
    for col in columns:
        print(f"   {col['column_name']}: {col['data_type']}")

    # Check sample data from hfj_res_ver
    print("\n2. Sample row from hfj_res_ver:")
    sql = """
        SELECT *
        FROM hfj_res_ver
        LIMIT 1
    """
    rows = await client.execute_query(sql)
    if rows:
        print(f"   Columns available: {list(rows[0].keys())}")

        # Check which column contains the JSONB resource
        for key, value in rows[0].items():
            if value and len(str(value)) > 100:  # Likely to be resource content
                print(f"   {key}: {str(value)[:200]}...")

    # Check how to join hfj_resource and hfj_res_ver
    print("\n3. Join relationship:")
    sql = """
        SELECT
            r.res_id,
            r.res_type,
            r.fhir_id,
            r.res_ver,
            v.pid as version_pid
        FROM hfj_resource r
        LEFT JOIN hfj_res_ver v ON r.res_ver = v.pid
        WHERE r.res_deleted_at IS NULL
        LIMIT 1
    """
    try:
        rows = await client.execute_query(sql)
        if rows:
            print(f"   ✓ Join successful!")
            print(f"   Sample: {rows[0]}")
    except Exception as e:
        print(f"   ✗ Join failed: {e}")

        # Try alternative join
        print("\n   Trying alternative join...")
        sql = """
            SELECT
                r.res_id,
                r.res_type,
                r.fhir_id,
                r.res_ver,
                v.res_ver_pid
            FROM hfj_resource r
            LEFT JOIN hfj_res_ver v ON r.res_ver = v.res_ver_pid
            WHERE r.res_deleted_at IS NULL
            LIMIT 1
        """
        rows = await client.execute_query(sql)
        if rows:
            print(f"   ✓ Alternative join successful!")
            print(f"   Sample: {rows[0]}")

    print("\n" + "=" * 60)

    await close_hapi_db_client()


if __name__ == "__main__":
    asyncio.run(main())
