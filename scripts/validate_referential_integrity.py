#!/usr/bin/env python3
"""
Referential Integrity Validator for Materialized Views

Validates that foreign key relationships between materialized views are correct.

Tests:
1. Foreign Key Existence: All referenced IDs exist in parent tables
2. Reference Format: All FHIR references follow correct format
3. Bidirectional Consistency: Extracted IDs match full references
4. Cardinality: Relationships follow expected patterns (1:N, etc.)
5. Performance: JOINs execute efficiently

Usage:
    python scripts/validate_referential_integrity.py
"""

import asyncio
import asyncpg
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from datetime import datetime


@dataclass
class ValidationResult:
    """Result of a single validation test"""
    test_name: str
    passed: bool
    total_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    orphaned_count: int = 0
    execution_time_ms: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sample_errors: List[Dict] = field(default_factory=list)

    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_count == 0:
            return 100.0
        return (self.valid_count / self.total_count) * 100.0


@dataclass
class IntegrityReport:
    """Complete referential integrity report"""
    schema_name: str
    timestamp: datetime
    overall_passed: bool
    results: List[ValidationResult]
    summary: Dict[str, any] = field(default_factory=dict)

    def print_summary(self):
        """Print formatted summary"""
        print(f"\n{'='*70}")
        print(f"REFERENTIAL INTEGRITY VALIDATION REPORT")
        print(f"{'='*70}")
        print(f"Schema: {self.schema_name}")
        print(f"Timestamp: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Overall Status: {'✅ PASSED' if self.overall_passed else '❌ FAILED'}")
        print(f"{'='*70}\n")

        for result in self.results:
            status = "✅ PASS" if result.passed else "❌ FAIL"
            print(f"{status} {result.test_name}")
            print(f"  Total: {result.total_count:,}")
            print(f"  Valid: {result.valid_count:,} ({result.success_rate():.2f}%)")

            if result.invalid_count > 0:
                print(f"  ⚠️  Invalid: {result.invalid_count:,}")

            if result.orphaned_count > 0:
                print(f"  ⚠️  Orphaned: {result.orphaned_count:,}")

            if result.execution_time_ms > 0:
                print(f"  Time: {result.execution_time_ms:.2f}ms")

            if result.errors:
                print(f"  Errors:")
                for error in result.errors[:3]:  # Show first 3 errors
                    print(f"    - {error}")
                if len(result.errors) > 3:
                    print(f"    ... and {len(result.errors) - 3} more")

            if result.warnings:
                print(f"  Warnings:")
                for warning in result.warnings[:2]:
                    print(f"    - {warning}")

            print()

        # Summary statistics
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r.passed)
        print(f"{'='*70}")
        print(f"SUMMARY: {passed_tests}/{total_tests} tests passed")
        print(f"{'='*70}\n")


class ReferentialIntegrityValidator:
    """Validator for materialized view referential integrity"""

    def __init__(self, conn: asyncpg.Connection, schema_name: str = "sqlonfhir"):
        """
        Initialize validator

        Args:
            conn: Database connection
            schema_name: Schema containing materialized views
        """
        self.conn = conn
        self.schema_name = schema_name
        self.results: List[ValidationResult] = []

    async def validate_all(self) -> IntegrityReport:
        """
        Run all validation tests

        Returns:
            Complete integrity report
        """
        print(f"\n{'='*70}")
        print(f"Starting Referential Integrity Validation")
        print(f"Schema: {self.schema_name}")
        print(f"{'='*70}\n")

        timestamp = datetime.now()

        # Run all validation tests
        await self._validate_patient_references_in_conditions()
        await self._validate_patient_references_in_observations()
        await self._validate_reference_format_consistency()
        await self._validate_dual_column_consistency()
        await self._validate_join_performance()
        await self._validate_cardinality()

        # Determine overall pass/fail
        overall_passed = all(r.passed for r in self.results)

        report = IntegrityReport(
            schema_name=self.schema_name,
            timestamp=timestamp,
            overall_passed=overall_passed,
            results=self.results,
            summary={
                'total_tests': len(self.results),
                'passed_tests': sum(1 for r in self.results if r.passed),
                'failed_tests': sum(1 for r in self.results if not r.passed),
            }
        )

        return report

    async def _validate_patient_references_in_conditions(self):
        """Validate that all condition.patient_id values exist in patient_demographics"""
        print("Test 1: Validating patient references in condition_simple...")

        start_time = asyncio.get_event_loop().time()

        try:
            # Check if views exist
            condition_exists = await self._check_view_exists('condition_simple')
            patient_exists = await self._check_view_exists('patient_demographics')

            if not condition_exists or not patient_exists:
                self.results.append(ValidationResult(
                    test_name="Patient References in Conditions",
                    passed=False,
                    errors=["Required views do not exist"]
                ))
                return

            # Get total condition count
            total_result = await self.conn.fetchrow(
                f"SELECT COUNT(*) as count FROM {self.schema_name}.condition_simple WHERE patient_id IS NOT NULL"
            )
            total_count = total_result['count']

            # Count conditions with valid patient references
            valid_result = await self.conn.fetchrow(f"""
                SELECT COUNT(*) as count
                FROM {self.schema_name}.condition_simple c
                INNER JOIN {self.schema_name}.patient_demographics p
                    ON c.patient_id = p.patient_id
                WHERE c.patient_id IS NOT NULL
            """)
            valid_count = valid_result['count']

            # Find orphaned conditions (patient_id doesn't exist in patients)
            orphaned_result = await self.conn.fetchrow(f"""
                SELECT COUNT(*) as count
                FROM {self.schema_name}.condition_simple c
                LEFT JOIN {self.schema_name}.patient_demographics p
                    ON c.patient_id = p.patient_id
                WHERE c.patient_id IS NOT NULL
                  AND p.patient_id IS NULL
            """)
            orphaned_count = orphaned_result['count']

            # Get sample orphaned records
            sample_errors = []
            if orphaned_count > 0:
                orphaned_samples = await self.conn.fetch(f"""
                    SELECT c.id, c.patient_id, c.patient_ref, c.icd10_code
                    FROM {self.schema_name}.condition_simple c
                    LEFT JOIN {self.schema_name}.patient_demographics p
                        ON c.patient_id = p.patient_id
                    WHERE c.patient_id IS NOT NULL
                      AND p.patient_id IS NULL
                    LIMIT 5
                """)
                sample_errors = [dict(row) for row in orphaned_samples]

            execution_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            passed = orphaned_count == 0
            warnings = []
            if orphaned_count > 0:
                warnings.append(f"Found {orphaned_count} conditions referencing non-existent patients")

            result = ValidationResult(
                test_name="Patient References in Conditions",
                passed=passed,
                total_count=total_count,
                valid_count=valid_count,
                invalid_count=0,
                orphaned_count=orphaned_count,
                execution_time_ms=execution_time_ms,
                warnings=warnings,
                sample_errors=sample_errors
            )

            self.results.append(result)
            print(f"  ✓ Completed ({execution_time_ms:.2f}ms)\n")

        except Exception as e:
            result = ValidationResult(
                test_name="Patient References in Conditions",
                passed=False,
                errors=[str(e)]
            )
            self.results.append(result)
            print(f"  ✗ Failed: {e}\n")

    async def _validate_patient_references_in_observations(self):
        """Validate that all observation.patient_id values exist in patient_demographics"""
        print("Test 2: Validating patient references in observation_labs...")

        start_time = asyncio.get_event_loop().time()

        try:
            obs_exists = await self._check_view_exists('observation_labs')
            patient_exists = await self._check_view_exists('patient_demographics')

            if not obs_exists or not patient_exists:
                self.results.append(ValidationResult(
                    test_name="Patient References in Observations",
                    passed=False,
                    errors=["Required views do not exist"]
                ))
                return

            total_result = await self.conn.fetchrow(
                f"SELECT COUNT(*) as count FROM {self.schema_name}.observation_labs WHERE patient_id IS NOT NULL"
            )
            total_count = total_result['count']

            valid_result = await self.conn.fetchrow(f"""
                SELECT COUNT(*) as count
                FROM {self.schema_name}.observation_labs o
                INNER JOIN {self.schema_name}.patient_demographics p
                    ON o.patient_id = p.patient_id
                WHERE o.patient_id IS NOT NULL
            """)
            valid_count = valid_result['count']

            orphaned_result = await self.conn.fetchrow(f"""
                SELECT COUNT(*) as count
                FROM {self.schema_name}.observation_labs o
                LEFT JOIN {self.schema_name}.patient_demographics p
                    ON o.patient_id = p.patient_id
                WHERE o.patient_id IS NOT NULL
                  AND p.patient_id IS NULL
            """)
            orphaned_count = orphaned_result['count']

            execution_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            passed = orphaned_count == 0
            warnings = []
            if orphaned_count > 0:
                warnings.append(f"Found {orphaned_count} observations referencing non-existent patients")

            result = ValidationResult(
                test_name="Patient References in Observations",
                passed=passed,
                total_count=total_count,
                valid_count=valid_count,
                orphaned_count=orphaned_count,
                execution_time_ms=execution_time_ms,
                warnings=warnings
            )

            self.results.append(result)
            print(f"  ✓ Completed ({execution_time_ms:.2f}ms)\n")

        except Exception as e:
            result = ValidationResult(
                test_name="Patient References in Observations",
                passed=False,
                errors=[str(e)]
            )
            self.results.append(result)
            print(f"  ✗ Failed: {e}\n")

    async def _validate_reference_format_consistency(self):
        """Validate that all FHIR references follow correct format"""
        print("Test 3: Validating FHIR reference format consistency...")

        start_time = asyncio.get_event_loop().time()

        try:
            # Check condition_simple.patient_ref format
            condition_result = await self.conn.fetchrow(f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN patient_ref LIKE 'Patient/%' THEN 1 ELSE 0 END) as valid_format
                FROM {self.schema_name}.condition_simple
                WHERE patient_ref IS NOT NULL
            """)

            # Check observation_labs.patient_ref format
            obs_result = await self.conn.fetchrow(f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN patient_ref LIKE 'Patient/%' THEN 1 ELSE 0 END) as valid_format
                FROM {self.schema_name}.observation_labs
                WHERE patient_ref IS NOT NULL
            """)

            total_refs = condition_result['total'] + obs_result['total']
            valid_refs = condition_result['valid_format'] + obs_result['valid_format']
            invalid_refs = total_refs - valid_refs

            execution_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            passed = invalid_refs == 0
            errors = []
            if invalid_refs > 0:
                errors.append(f"Found {invalid_refs} references not following 'Patient/{{id}}' format")

            result = ValidationResult(
                test_name="FHIR Reference Format Consistency",
                passed=passed,
                total_count=total_refs,
                valid_count=valid_refs,
                invalid_count=invalid_refs,
                execution_time_ms=execution_time_ms,
                errors=errors
            )

            self.results.append(result)
            print(f"  ✓ Completed ({execution_time_ms:.2f}ms)\n")

        except Exception as e:
            result = ValidationResult(
                test_name="FHIR Reference Format Consistency",
                passed=False,
                errors=[str(e)]
            )
            self.results.append(result)
            print(f"  ✗ Failed: {e}\n")

    async def _validate_dual_column_consistency(self):
        """Validate that patient_id matches extracted ID from patient_ref"""
        print("Test 4: Validating dual column consistency (patient_ref vs patient_id)...")

        start_time = asyncio.get_event_loop().time()

        try:
            # Check condition_simple
            condition_result = await self.conn.fetchrow(f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE
                        WHEN patient_id = SPLIT_PART(patient_ref, '/', 2) THEN 1
                        ELSE 0
                    END) as consistent
                FROM {self.schema_name}.condition_simple
                WHERE patient_ref IS NOT NULL AND patient_id IS NOT NULL
            """)

            # Check observation_labs
            obs_result = await self.conn.fetchrow(f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE
                        WHEN patient_id = SPLIT_PART(patient_ref, '/', 2) THEN 1
                        ELSE 0
                    END) as consistent
                FROM {self.schema_name}.observation_labs
                WHERE patient_ref IS NOT NULL AND patient_id IS NOT NULL
            """)

            total_records = condition_result['total'] + obs_result['total']
            consistent_records = condition_result['consistent'] + obs_result['consistent']
            inconsistent_records = total_records - consistent_records

            execution_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            passed = inconsistent_records == 0
            errors = []
            if inconsistent_records > 0:
                errors.append(
                    f"Found {inconsistent_records} records where patient_id doesn't match extracted ID from patient_ref"
                )

            result = ValidationResult(
                test_name="Dual Column Consistency",
                passed=passed,
                total_count=total_records,
                valid_count=consistent_records,
                invalid_count=inconsistent_records,
                execution_time_ms=execution_time_ms,
                errors=errors
            )

            self.results.append(result)
            print(f"  ✓ Completed ({execution_time_ms:.2f}ms)\n")

        except Exception as e:
            result = ValidationResult(
                test_name="Dual Column Consistency",
                passed=False,
                errors=[str(e)]
            )
            self.results.append(result)
            print(f"  ✗ Failed: {e}\n")

    async def _validate_join_performance(self):
        """Validate that JOINs execute efficiently"""
        print("Test 5: Validating JOIN performance...")

        start_time = asyncio.get_event_loop().time()

        try:
            # Test JOIN performance (should be <100ms)
            query = f"""
                SELECT COUNT(*)
                FROM {self.schema_name}.condition_simple c
                INNER JOIN {self.schema_name}.patient_demographics p
                    ON c.patient_id = p.patient_id
            """

            join_start = asyncio.get_event_loop().time()
            result = await self.conn.fetchrow(query)
            join_time_ms = (asyncio.get_event_loop().time() - join_start) * 1000

            execution_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            # Performance threshold: JOINs should be <100ms
            threshold_ms = 100.0
            passed = join_time_ms < threshold_ms

            warnings = []
            if not passed:
                warnings.append(f"JOIN took {join_time_ms:.2f}ms (threshold: {threshold_ms}ms)")

            result_obj = ValidationResult(
                test_name="JOIN Performance",
                passed=passed,
                total_count=result['count'],
                valid_count=result['count'],
                execution_time_ms=join_time_ms,
                warnings=warnings
            )

            self.results.append(result_obj)
            print(f"  ✓ Completed (JOIN time: {join_time_ms:.2f}ms)\n")

        except Exception as e:
            result = ValidationResult(
                test_name="JOIN Performance",
                passed=False,
                errors=[str(e)]
            )
            self.results.append(result)
            print(f"  ✗ Failed: {e}\n")

    async def _validate_cardinality(self):
        """Validate relationship cardinality (1:N for Patient → Conditions)"""
        print("Test 6: Validating relationship cardinality...")

        start_time = asyncio.get_event_loop().time()

        try:
            # Get patient counts
            patient_count_result = await self.conn.fetchrow(
                f"SELECT COUNT(*) as count FROM {self.schema_name}.patient_demographics"
            )
            patient_count = patient_count_result['count']

            # Get condition counts
            condition_count_result = await self.conn.fetchrow(
                f"SELECT COUNT(*) as count FROM {self.schema_name}.condition_simple WHERE patient_id IS NOT NULL"
            )
            condition_count = condition_count_result['count']

            # Get patients with conditions
            patients_with_conditions_result = await self.conn.fetchrow(f"""
                SELECT COUNT(DISTINCT patient_id) as count
                FROM {self.schema_name}.condition_simple
                WHERE patient_id IS NOT NULL
            """)
            patients_with_conditions = patients_with_conditions_result['count']

            execution_time_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            # Cardinality test: conditions should be >= patients with conditions (1:N)
            passed = condition_count >= patients_with_conditions

            ratio = condition_count / patients_with_conditions if patients_with_conditions > 0 else 0

            warnings = []
            warnings.append(f"Patients: {patient_count:,}")
            warnings.append(f"Conditions: {condition_count:,}")
            warnings.append(f"Patients with conditions: {patients_with_conditions:,}")
            warnings.append(f"Avg conditions per patient: {ratio:.2f}")

            result = ValidationResult(
                test_name="Relationship Cardinality",
                passed=passed,
                total_count=condition_count,
                valid_count=condition_count,
                execution_time_ms=execution_time_ms,
                warnings=warnings
            )

            self.results.append(result)
            print(f"  ✓ Completed ({execution_time_ms:.2f}ms)\n")

        except Exception as e:
            result = ValidationResult(
                test_name="Relationship Cardinality",
                passed=False,
                errors=[str(e)]
            )
            self.results.append(result)
            print(f"  ✗ Failed: {e}\n")

    async def _check_view_exists(self, view_name: str) -> bool:
        """Check if materialized view exists"""
        result = await self.conn.fetchrow(f"""
            SELECT EXISTS (
                SELECT 1
                FROM pg_matviews
                WHERE schemaname = $1 AND matviewname = $2
            ) as exists
        """, self.schema_name, view_name)

        return result['exists']


async def main():
    """Run referential integrity validation"""
    hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")

    print(f"Connecting to: {hapi_db_url}")
    conn = await asyncpg.connect(hapi_db_url)

    try:
        validator = ReferentialIntegrityValidator(conn)
        report = await validator.validate_all()

        report.print_summary()

        # Exit with appropriate code
        exit_code = 0 if report.overall_passed else 1
        exit(exit_code)

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
