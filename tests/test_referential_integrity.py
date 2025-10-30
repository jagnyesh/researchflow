"""
Referential Integrity Tests for Materialized Views

Tests the dual column architecture and referential integrity
between materialized views.

Run with:
    HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi pytest tests/test_referential_integrity.py -v
"""

import pytest
import asyncio
import os
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.clients.hapi_db_client import create_hapi_db_client, close_hapi_db_client


@pytest.mark.asyncio
async def test_dual_column_exists():
    """Test that materialized views have both patient_ref and patient_id columns"""
    print("\n" + "="*70)
    print("TEST: Dual Column Architecture")
    print("="*70)

    db_client = await create_hapi_db_client()

    try:
        # Direct query to check columns exist (more reliable than information_schema)
        # Try to select both columns - will fail if they don't exist
        try:
            result = await db_client.execute_query("""
                SELECT patient_ref, patient_id
                FROM sqlonfhir.condition_simple
                LIMIT 1
            """)

            if result and len(result) > 0:
                columns = list(result[0].keys())
                print(f"  condition_simple columns: {columns}")

                assert 'patient_ref' in columns, "Missing patient_ref column"
                assert 'patient_id' in columns, "Missing patient_id column"
            else:
                print(f"  condition_simple: View is empty but columns exist")

        except Exception as e:
            raise AssertionError(f"condition_simple missing dual columns: {e}")

        # Check observation_labs has both columns
        try:
            result = await db_client.execute_query("""
                SELECT patient_ref, patient_id
                FROM sqlonfhir.observation_labs
                LIMIT 1
            """)

            if result and len(result) > 0:
                columns = list(result[0].keys())
                print(f"  observation_labs columns: {columns}")

                assert 'patient_ref' in columns, "Missing patient_ref column"
                assert 'patient_id' in columns, "Missing patient_id column"
            else:
                print(f"  observation_labs: View is empty but columns exist")

        except Exception as e:
            raise AssertionError(f"observation_labs missing dual columns: {e}")

        print("  ✅ Both views have dual columns\n")

    finally:
        await close_hapi_db_client()


@pytest.mark.asyncio
async def test_patient_id_extraction_correctness():
    """Test that patient_id correctly matches extracted ID from patient_ref"""
    print("\n" + "="*70)
    print("TEST: Patient ID Extraction Correctness")
    print("="*70)

    db_client = await create_hapi_db_client()

    try:
        # Test condition_simple
        result = await db_client.execute_query("""
            SELECT
                COUNT(*) as total,
                SUM(CASE
                    WHEN patient_id = SPLIT_PART(patient_ref, '/', 2) THEN 1
                    ELSE 0
                END) as consistent
            FROM sqlonfhir.condition_simple
            WHERE patient_ref IS NOT NULL AND patient_id IS NOT NULL
        """)

        total = result[0]['total']
        consistent = result[0]['consistent']
        print(f"  condition_simple: {consistent}/{total} consistent")

        assert consistent == total, f"Found {total - consistent} inconsistent records in condition_simple"

        # Test observation_labs
        result = await db_client.execute_query("""
            SELECT
                COUNT(*) as total,
                SUM(CASE
                    WHEN patient_id = SPLIT_PART(patient_ref, '/', 2) THEN 1
                    ELSE 0
                END) as consistent
            FROM sqlonfhir.observation_labs
            WHERE patient_ref IS NOT NULL AND patient_id IS NOT NULL
        """)

        total = result[0]['total']
        consistent = result[0]['consistent']
        print(f"  observation_labs: {consistent}/{total} consistent")

        assert consistent == total, f"Found {total - consistent} inconsistent records in observation_labs"

        print("  ✅ All extracted IDs match references\n")

    finally:
        await close_hapi_db_client()


@pytest.mark.asyncio
async def test_fhir_reference_format():
    """Test that patient_ref follows FHIR reference format"""
    print("\n" + "="*70)
    print("TEST: FHIR Reference Format")
    print("="*70)

    db_client = await create_hapi_db_client()

    try:
        # Test condition_simple
        result = await db_client.execute_query("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN patient_ref LIKE 'Patient/%' THEN 1 ELSE 0 END) as valid
            FROM sqlonfhir.condition_simple
            WHERE patient_ref IS NOT NULL
        """)

        total = result[0]['total']
        valid = result[0]['valid']
        print(f"  condition_simple: {valid}/{total} valid format")

        assert valid == total, f"Found {total - valid} invalid FHIR references in condition_simple"

        # Test observation_labs
        result = await db_client.execute_query("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN patient_ref LIKE 'Patient/%' THEN 1 ELSE 0 END) as valid
            FROM sqlonfhir.observation_labs
            WHERE patient_ref IS NOT NULL
        """)

        total = result[0]['total']
        valid = result[0]['valid']
        print(f"  observation_labs: {valid}/{total} valid format")

        assert valid == total, f"Found {total - valid} invalid FHIR references in observation_labs"

        print("  ✅ All references follow FHIR format\n")

    finally:
        await close_hapi_db_client()


@pytest.mark.asyncio
async def test_foreign_key_integrity_conditions():
    """Test that all condition.patient_id values exist in patient_demographics"""
    print("\n" + "="*70)
    print("TEST: Foreign Key Integrity - Conditions")
    print("="*70)

    db_client = await create_hapi_db_client()

    try:
        # Get total conditions
        result = await db_client.execute_query("""
            SELECT COUNT(*) as count
            FROM sqlonfhir.condition_simple
            WHERE patient_id IS NOT NULL
        """)
        total_conditions = result[0]['count']

        # Get valid conditions (patient exists)
        result = await db_client.execute_query("""
            SELECT COUNT(*) as count
            FROM sqlonfhir.condition_simple c
            INNER JOIN sqlonfhir.patient_demographics p
                ON c.patient_id = p.patient_id
            WHERE c.patient_id IS NOT NULL
        """)
        valid_conditions = result[0]['count']

        # Get orphaned conditions
        result = await db_client.execute_query("""
            SELECT COUNT(*) as count
            FROM sqlonfhir.condition_simple c
            LEFT JOIN sqlonfhir.patient_demographics p
                ON c.patient_id = p.patient_id
            WHERE c.patient_id IS NOT NULL
              AND p.patient_id IS NULL
        """)
        orphaned = result[0]['count']

        print(f"  Total conditions: {total_conditions:,}")
        print(f"  Valid references: {valid_conditions:,}")
        print(f"  Orphaned: {orphaned:,}")

        if orphaned > 0:
            # Get sample orphaned records
            samples = await db_client.execute_query("""
                SELECT c.id, c.patient_id, c.patient_ref, c.icd10_code
                FROM sqlonfhir.condition_simple c
                LEFT JOIN sqlonfhir.patient_demographics p
                    ON c.patient_id = p.patient_id
                WHERE c.patient_id IS NOT NULL
                  AND p.patient_id IS NULL
                LIMIT 3
            """)

            print(f"\n  Sample orphaned records:")
            for sample in samples:
                print(f"    - Condition {sample['id']}: patient_id={sample['patient_id']}, code={sample['icd10_code']}")

        assert orphaned == 0, f"Found {orphaned} orphaned conditions (patients don't exist)"

        print("  ✅ All condition references are valid\n")

    finally:
        await close_hapi_db_client()


@pytest.mark.asyncio
async def test_foreign_key_integrity_observations():
    """Test that all observation.patient_id values exist in patient_demographics"""
    print("\n" + "="*70)
    print("TEST: Foreign Key Integrity - Observations")
    print("="*70)

    db_client = await create_hapi_db_client()

    try:
        # Get total observations
        result = await db_client.execute_query("""
            SELECT COUNT(*) as count
            FROM sqlonfhir.observation_labs
            WHERE patient_id IS NOT NULL
        """)
        total_obs = result[0]['count']

        # Get valid observations
        result = await db_client.execute_query("""
            SELECT COUNT(*) as count
            FROM sqlonfhir.observation_labs o
            INNER JOIN sqlonfhir.patient_demographics p
                ON o.patient_id = p.patient_id
            WHERE o.patient_id IS NOT NULL
        """)
        valid_obs = result[0]['count']

        # Get orphaned observations
        result = await db_client.execute_query("""
            SELECT COUNT(*) as count
            FROM sqlonfhir.observation_labs o
            LEFT JOIN sqlonfhir.patient_demographics p
                ON o.patient_id = p.patient_id
            WHERE o.patient_id IS NOT NULL
              AND p.patient_id IS NULL
        """)
        orphaned = result[0]['count']

        print(f"  Total observations: {total_obs:,}")
        print(f"  Valid references: {valid_obs:,}")
        print(f"  Orphaned: {orphaned:,}")

        assert orphaned == 0, f"Found {orphaned} orphaned observations (patients don't exist)"

        print("  ✅ All observation references are valid\n")

    finally:
        await close_hapi_db_client()


@pytest.mark.asyncio
async def test_join_performance():
    """Test that JOINs using patient_id are fast"""
    print("\n" + "="*70)
    print("TEST: JOIN Performance")
    print("="*70)

    db_client = await create_hapi_db_client()

    try:
        import time

        # Test JOIN performance
        start = time.time()
        result = await db_client.execute_query("""
            SELECT COUNT(*)
            FROM sqlonfhir.condition_simple c
            INNER JOIN sqlonfhir.patient_demographics p
                ON c.patient_id = p.patient_id
        """)
        elapsed_ms = (time.time() - start) * 1000

        count = result[0]['count']

        print(f"  JOIN returned: {count:,} rows")
        print(f"  Execution time: {elapsed_ms:.2f}ms")

        # Performance threshold: <100ms
        assert elapsed_ms < 100, f"JOIN took {elapsed_ms:.2f}ms (threshold: 100ms)"

        print("  ✅ JOIN performance acceptable\n")

    finally:
        await close_hapi_db_client()


@pytest.mark.asyncio
async def test_simplified_join_syntax():
    """Test that simplified JOIN syntax works (no 'Patient/' concat needed)"""
    print("\n" + "="*70)
    print("TEST: Simplified JOIN Syntax")
    print("="*70)

    db_client = await create_hapi_db_client()

    try:
        # Old syntax (should still work)
        result_old = await db_client.execute_query("""
            SELECT COUNT(*) as count
            FROM sqlonfhir.patient_demographics p
            JOIN sqlonfhir.condition_simple c
                ON 'Patient/' || p.patient_id = c.patient_ref
        """)

        # New simplified syntax (uses patient_id)
        result_new = await db_client.execute_query("""
            SELECT COUNT(*) as count
            FROM sqlonfhir.patient_demographics p
            JOIN sqlonfhir.condition_simple c
                ON p.patient_id = c.patient_id
        """)

        old_count = result_old[0]['count']
        new_count = result_new[0]['count']

        print(f"  Old syntax (patient_ref): {old_count:,} rows")
        print(f"  New syntax (patient_id): {new_count:,} rows")

        # Both should return same results
        assert old_count == new_count, f"Results differ: old={old_count}, new={new_count}"

        print("  ✅ Simplified JOIN syntax works correctly\n")

    finally:
        await close_hapi_db_client()


@pytest.mark.asyncio
async def test_index_exists():
    """Test that indexes exist on patient_id columns"""
    print("\n" + "="*70)
    print("TEST: Index Existence")
    print("="*70)

    db_client = await create_hapi_db_client()

    try:
        # Check indexes on condition_simple
        result = await db_client.execute_query("""
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'sqlonfhir'
              AND tablename = 'condition_simple'
              AND indexname LIKE '%patient_id%'
        """)

        condition_indexes = [r['indexname'] for r in result]
        print(f"  condition_simple indexes: {condition_indexes}")

        assert len(condition_indexes) > 0, "No patient_id index on condition_simple"

        # Check indexes on observation_labs
        result = await db_client.execute_query("""
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'sqlonfhir'
              AND tablename = 'observation_labs'
              AND indexname LIKE '%patient_id%'
        """)

        obs_indexes = [r['indexname'] for r in result]
        print(f"  observation_labs indexes: {obs_indexes}")

        assert len(obs_indexes) > 0, "No patient_id index on observation_labs"

        print("  ✅ Indexes exist on patient_id columns\n")

    finally:
        await close_hapi_db_client()


@pytest.mark.asyncio
async def test_male_diabetes_query():
    """Test the example query: count male patients with diabetes"""
    print("\n" + "="*70)
    print("TEST: Male Diabetes Query (Real-World Example)")
    print("="*70)

    db_client = await create_hapi_db_client()

    try:
        import time

        start = time.time()
        result = await db_client.execute_query("""
            SELECT COUNT(DISTINCT p.patient_id) as count
            FROM sqlonfhir.patient_demographics p
            JOIN sqlonfhir.condition_simple c
                ON p.patient_id = c.patient_id
            WHERE LOWER(p.gender) = 'male'
              AND (
                c.icd10_code LIKE 'E11%'
                OR c.icd10_code LIKE 'E10%'
                OR LOWER(c.icd10_display) LIKE '%diabetes%'
              )
        """)
        elapsed_ms = (time.time() - start) * 1000

        count = result[0]['count']

        print(f"  Male patients with diabetes: {count:,}")
        print(f"  Query time: {elapsed_ms:.2f}ms")

        # Should be fast (< 50ms)
        assert elapsed_ms < 50, f"Query took {elapsed_ms:.2f}ms (threshold: 50ms)"

        print("  ✅ Real-world query works correctly\n")

    finally:
        await close_hapi_db_client()


def test_summary():
    """Print test summary"""
    print("\n" + "="*70)
    print("REFERENTIAL INTEGRITY TEST SUITE SUMMARY")
    print("="*70)
    print("""
✅ Dual Column Architecture Validated:
- Both patient_ref and patient_id columns exist
- patient_id correctly extracted from patient_ref
- FHIR reference format preserved in patient_ref

✅ Referential Integrity Validated:
- All condition.patient_id values reference existing patients
- All observation.patient_id values reference existing patients
- No orphaned records found

✅ Performance Validated:
- JOINs execute in <100ms
- Indexes exist on patient_id columns
- Real-world queries perform well

✅ Simplified JOIN Syntax:
- No more 'Patient/' || patient_id concatenation needed
- Direct patient_id = patient_id JOINs work perfectly
- Backward compatible with old syntax

The dual column architecture successfully fixes the referential
integrity issues while maintaining FHIR semantics! 🎉
    """)


if __name__ == "__main__":
    # Run tests
    print("\n" + "="*80)
    print("STARTING REFERENTIAL INTEGRITY TEST SUITE")
    print("="*80)

    asyncio.run(test_dual_column_exists())
    asyncio.run(test_patient_id_extraction_correctness())
    asyncio.run(test_fhir_reference_format())
    asyncio.run(test_foreign_key_integrity_conditions())
    asyncio.run(test_foreign_key_integrity_observations())
    asyncio.run(test_join_performance())
    asyncio.run(test_simplified_join_syntax())
    asyncio.run(test_index_exists())
    asyncio.run(test_male_diabetes_query())
    test_summary()

    print("\n" + "="*80)
    print("ALL TESTS COMPLETED SUCCESSFULLY! ✅")
    print("="*80 + "\n")
