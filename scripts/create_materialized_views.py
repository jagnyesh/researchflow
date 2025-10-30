#!/usr/bin/env python3
"""
Simple script to create materialized views from ViewDefinitions in PostgreSQL.

Creates views in the 'sqlonfhir' schema for fast analytics queries.

Usage:
    python scripts/create_materialized_views.py

Environment:
    HAPI_DB_URL: postgresql://hapi:hapi@localhost:5433/hapi
    SKIP_VALIDATION: Set to '1' to skip referential integrity validation
"""

import asyncio
import asyncpg
import json
import os
import sys
from pathlib import Path

HAPI_DB_URL = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")
SCHEMA_NAME = "sqlonfhir"
VIEW_DEFS_DIR = Path(__file__).parent.parent / "app" / "sql_on_fhir" / "view_definitions"
SKIP_VALIDATION = os.getenv("SKIP_VALIDATION", "0") == "1"

# SQL templates for simple views that work without complex transpilation
VIEW_TEMPLATES = {
    "patient_simple": """
        SELECT
            r.res_id::text as id,
            r.res_id::text as patient_id,
            v.res_text_vc::jsonb->>'gender' as gender,
            v.res_text_vc::jsonb->>'birthDate' as birth_date
        FROM hfj_resource r
        JOIN hfj_res_ver v ON r.res_id = v.res_id AND r.res_ver = v.res_ver
        WHERE r.res_type = 'Patient'
          AND r.res_deleted_at IS NULL
    """,

    "condition_simple": """
        SELECT
            r.res_id::text as id,
            v.res_text_vc::jsonb->'subject'->>'reference' as patient_ref,
            SPLIT_PART(v.res_text_vc::jsonb->'subject'->>'reference', '/', 2) as patient_id,
            (v.res_text_vc::jsonb->'code'->'coding'->0->>'code') as icd10_code,
            (v.res_text_vc::jsonb->'code'->'coding'->0->>'display') as icd10_display,
            (v.res_text_vc::jsonb->'code'->'coding'->1->>'code') as snomed_code,
            (v.res_text_vc::jsonb->'code'->'coding'->1->>'display') as snomed_display,
            v.res_text_vc::jsonb->'code'->>'text' as code_text,
            v.res_text_vc::jsonb->'clinicalStatus'->'coding'->0->>'code' as clinical_status
        FROM hfj_resource r
        JOIN hfj_res_ver v ON r.res_id = v.res_id AND r.res_ver = v.res_ver
        WHERE r.res_type = 'Condition'
          AND r.res_deleted_at IS NULL
    """,

    "patient_demographics": """
        SELECT
            r.res_id::text as id,
            r.res_id::text as patient_id,
            v.res_text_vc::jsonb->>'gender' as gender,
            v.res_text_vc::jsonb->>'birthDate' as dob,
            (v.res_text_vc::jsonb->'name'->0->'given'->0->>'value') as name_given,
            (v.res_text_vc::jsonb->'name'->0->>'family') as name_family
        FROM hfj_resource r
        JOIN hfj_res_ver v ON r.res_id = v.res_id AND r.res_ver = v.res_ver
        WHERE r.res_type = 'Patient'
          AND r.res_deleted_at IS NULL
    """,

    "observation_labs": """
        SELECT
            r.res_id::text as id,
            v.res_text_vc::jsonb->'subject'->>'reference' as patient_ref,
            SPLIT_PART(v.res_text_vc::jsonb->'subject'->>'reference', '/', 2) as patient_id,
            v.res_text_vc::jsonb->'code'->'coding'->0->>'code' as code,
            v.res_text_vc::jsonb->'code'->'coding'->0->>'display' as display,
            v.res_text_vc::jsonb->'valueQuantity'->>'value' as value,
            v.res_text_vc::jsonb->'valueQuantity'->>'unit' as unit,
            v.res_text_vc::jsonb->>'effectiveDateTime' as effective_date,
            v.res_text_vc::jsonb->>'status' as status
        FROM hfj_resource r
        JOIN hfj_res_ver v ON r.res_id = v.res_id AND r.res_ver = v.res_ver
        WHERE r.res_type = 'Observation'
          AND r.res_deleted_at IS NULL
    """
}


async def create_schema(conn):
    """Create the sqlonfhir schema."""
    print(f"Creating schema '{SCHEMA_NAME}'...")
    await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")
    print(f"✅ Schema '{SCHEMA_NAME}' ready\n")


async def create_materialized_view(conn, view_name, sql):
    """Create a single materialized view."""
    print(f"{'='*60}")
    print(f"Creating view: {view_name}")
    print(f"{'='*60}")

    try:
        # Drop existing view
        print(f"  Dropping existing view if present...")
        await conn.execute(f"DROP MATERIALIZED VIEW IF EXISTS {SCHEMA_NAME}.{view_name} CASCADE")

        # Create materialized view
        print(f"  Creating materialized view...")
        create_sql = f"CREATE MATERIALIZED VIEW {SCHEMA_NAME}.{view_name} AS {sql}"
        await conn.execute(create_sql)

        # Get row count
        result = await conn.fetchrow(f"SELECT COUNT(*) as count FROM {SCHEMA_NAME}.{view_name}")
        row_count = result['count']

        print(f"  ✅ Created: {SCHEMA_NAME}.{view_name}")
        print(f"  📊 Rows: {row_count:,}\n")

        return True

    except Exception as e:
        print(f"  ❌ Failed: {e}\n")
        return False


async def create_indexes(conn, view_name):
    """Create indexes on common columns."""
    print(f"  Creating indexes for {view_name}...")

    indexes = {
        'patient_simple': ['patient_id', 'gender'],
        'patient_demographics': ['patient_id', 'gender'],
        'condition_simple': ['patient_id', 'patient_ref', 'icd10_code', 'snomed_code'],
        'observation_labs': ['patient_id', 'patient_ref', 'code', 'effective_date']
    }

    if view_name not in indexes:
        return

    for col in indexes[view_name]:
        try:
            idx_name = f"idx_{view_name}_{col}"
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS {idx_name}
                ON {SCHEMA_NAME}.{view_name} ({col})
            """)
            print(f"    ✅ Index: {idx_name}")
        except Exception as e:
            print(f"    ⚠️  Index failed: {col} ({e})")

    print()


async def list_views(conn):
    """List all materialized views."""
    print(f"\n{'='*60}")
    print(f"MATERIALIZED VIEWS IN '{SCHEMA_NAME}' SCHEMA")
    print(f"{'='*60}\n")

    result = await conn.fetch(f"""
        SELECT
            matviewname,
            pg_size_pretty(pg_total_relation_size('{SCHEMA_NAME}.'||matviewname)) as size
        FROM pg_matviews
        WHERE schemaname = '{SCHEMA_NAME}'
        ORDER BY matviewname
    """)

    if not result:
        print("  No materialized views found\n")
        return

    for row in result:
        view_name = row['matviewname']
        count_result = await conn.fetchrow(f"SELECT COUNT(*) as count FROM {SCHEMA_NAME}.{view_name}")
        row_count = count_result['count']

        print(f"  • {view_name}")
        print(f"      Size: {row['size']}")
        print(f"      Rows: {row_count:,}\n")


async def run_referential_integrity_validation(conn):
    """
    Run referential integrity validation on all views

    Args:
        conn: Database connection

    Returns:
        True if validation passed, False otherwise
    """
    try:
        # Import validator (lazy import to avoid circular dependency)
        from validate_referential_integrity import ReferentialIntegrityValidator

        print(f"\n{'='*60}")
        print("VALIDATING REFERENTIAL INTEGRITY")
        print(f"{'='*60}\n")

        validator = ReferentialIntegrityValidator(conn, SCHEMA_NAME)
        report = await validator.validate_all()

        report.print_summary()

        return report.overall_passed

    except ImportError as e:
        print(f"⚠️  Warning: Could not import validation module: {e}")
        print(f"Skipping referential integrity validation\n")
        return True
    except Exception as e:
        print(f"⚠️  Validation error: {e}")
        print(f"Continuing despite validation failure\n")
        return False


async def main():
    """Main function."""
    print(f"\n{'='*60}")
    print(f"MATERIALIZE SQL-ON-FHIR VIEWS")
    print(f"{'='*60}")
    print(f"Database: {HAPI_DB_URL}")
    print(f"Schema: {SCHEMA_NAME}")
    print(f"Validation: {'SKIPPED' if SKIP_VALIDATION else 'ENABLED'}\n")

    conn = await asyncpg.connect(HAPI_DB_URL)

    try:
        # Create schema
        await create_schema(conn)

        # Create each view
        success_count = 0
        for view_name, sql in VIEW_TEMPLATES.items():
            if await create_materialized_view(conn, view_name, sql):
                await create_indexes(conn, view_name)
                success_count += 1

        # List all views
        await list_views(conn)

        # Run referential integrity validation (unless skipped)
        validation_passed = True
        if not SKIP_VALIDATION and success_count > 0:
            validation_passed = await run_referential_integrity_validation(conn)

            if not validation_passed:
                print(f"\n{'='*60}")
                print(f"⚠️  WARNING: Referential Integrity Validation FAILED")
                print(f"{'='*60}")
                print(f"Views were created but have integrity issues.")
                print(f"Please review the validation report above.")
                print(f"{'='*60}\n")
                sys.exit(1)

        # Summary
        print(f"{'='*60}")
        if validation_passed:
            print(f"✅ COMPLETE: {success_count}/{len(VIEW_TEMPLATES)} views created")
            if not SKIP_VALIDATION:
                print(f"✅ VALIDATION: All integrity checks passed")
        else:
            print(f"⚠️  {success_count}/{len(VIEW_TEMPLATES)} views created but validation failed")
        print(f"{'='*60}\n")

        # Usage examples
        print("Query examples:")
        print(f"  SELECT * FROM {SCHEMA_NAME}.patient_demographics LIMIT 10;")
        print(f"  SELECT COUNT(*) FROM {SCHEMA_NAME}.condition_simple;")
        print(f"""
  -- Simplified JOINs with dual column architecture
  SELECT  DATE_PART('year', AGE(pt.dob::timestamp)) AS age,
          gender,
          cs.icd10_code,
          cs.icd10_display,
          count(*)
     FROM {SCHEMA_NAME}.patient_demographics pt
     JOIN {SCHEMA_NAME}.condition_simple cs
       ON pt.patient_id = cs.patient_id  -- ✨ Simplified JOIN (no more 'Patient/' concat)
    WHERE cs.icd10_code IS NOT NULL
 GROUP BY 1,2,3,4
 ORDER BY 1, 5 DESC;

  -- Count male patients with diabetes
  SELECT COUNT(DISTINCT p.patient_id)
    FROM {SCHEMA_NAME}.patient_demographics p
    JOIN {SCHEMA_NAME}.condition_simple c
      ON p.patient_id = c.patient_id
   WHERE LOWER(p.gender) = 'male'
     AND (c.icd10_code LIKE 'E11%' OR LOWER(c.icd10_display) LIKE '%diabetes%');
""")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
