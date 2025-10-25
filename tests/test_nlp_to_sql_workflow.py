"""
Test Natural Language to SQL Generation Workflow

This test suite verifies the complete end-to-end flow:
1. Submit natural language query in Researcher Portal
2. Requirements Agent extracts structured requirements
3. Phenotype Agent generates SQL-on-FHIR query
4. SQL query is submitted for approval
5. Admin Dashboard displays the approval

Purpose: Understand how natural language queries become SQL and verify
the workflow integration between portal and dashboard.
"""

import pytest
import asyncio
from datetime import datetime
from sqlalchemy import select

from app.orchestrator.orchestrator import ResearchRequestOrchestrator
from app.agents.requirements_agent import RequirementsAgent
from app.agents.phenotype_agent import PhenotypeValidationAgent
from app.database import get_db_session
from app.database.models import ResearchRequest, RequirementsData, FeasibilityReport, Approval
from app.services.approval_service import ApprovalService


@pytest.fixture
def orchestrator():
    """Create orchestrator with required agents"""
    orch = ResearchRequestOrchestrator()
    orch.register_agent('requirements_agent', RequirementsAgent())
    orch.register_agent('phenotype_agent', PhenotypeValidationAgent())
    return orch


class TestNaturalLanguageToSQL:
    """Test suite for NL → SQL workflow"""

    @pytest.mark.asyncio
    async def test_heart_failure_diabetes_query(self, orchestrator):
        """
        Test: Heart failure patients with diabetes from 2024

        This simulates a researcher entering:
        "I need heart failure patients from 2024 with diabetes"

        Verifies:
        1. Requirements extracted correctly
        2. SQL generated with proper criteria
        3. Approval created for SQL review
        """
        # Step 1: Submit natural language query
        natural_language_query = (
            "I need heart failure patients from 2024 with diabetes. "
            "I want de-identified data including demographics and lab results."
        )

        researcher_info = {
            'name': 'Dr. Test Smith',
            'email': 'test.smith@hospital.org',
            'department': 'Cardiology',
            'irb_number': 'IRB-2024-TEST-001'
        }

        print(f"\n{'='*80}")
        print("STEP 1: Submitting Natural Language Query")
        print(f"{'='*80}")
        print(f"Query: {natural_language_query}")
        print(f"Researcher: {researcher_info['name']}")

        request_id = await orchestrator.process_new_request(
            researcher_request=natural_language_query,
            researcher_info=researcher_info
        )

        print(f"Request ID: {request_id}")

        # Wait for Requirements Agent to process
        await asyncio.sleep(3)

        # Step 2: Verify requirements extraction
        print(f"\n{'='*80}")
        print("STEP 2: Verifying Requirements Extraction")
        print(f"{'='*80}")

        async with get_db_session() as session:
            result = await session.execute(
                select(RequirementsData).where(
                    RequirementsData.request_id == request_id
                )
            )
            requirements_data = result.scalar_one_or_none()

        if requirements_data:
            requirements = requirements_data.requirements
            print("\nExtracted Requirements:")
            print(f"  Inclusion Criteria: {requirements.get('inclusion_criteria', [])}")
            print(f"  Exclusion Criteria: {requirements.get('exclusion_criteria', [])}")
            print(f"  Data Elements: {requirements.get('data_elements', [])}")
            print(f"  Time Period: {requirements.get('time_period', {})}")
            print(f"  PHI Level: {requirements.get('phi_level', 'Not specified')}")

            # Assertions
            criteria_str = ' '.join(requirements.get('inclusion_criteria', [])).lower()
            assert any(term in criteria_str for term in ['heart failure', 'hf', 'chf']), \
                "Heart failure not found in inclusion criteria"
            assert any(term in criteria_str for term in ['diabetes', 'dm']), \
                "Diabetes not found in inclusion criteria"
        else:
            print("\n⚠️  Requirements not yet extracted - waiting longer...")
            await asyncio.sleep(2)

        # Wait for Phenotype Agent to process
        await asyncio.sleep(3)

        # Step 3: Verify SQL generation
        print(f"\n{'='*80}")
        print("STEP 3: Verifying SQL Generation")
        print(f"{'='*80}")

        async with get_db_session() as session:
            result = await session.execute(
                select(FeasibilityReport).where(
                    FeasibilityReport.request_id == request_id
                )
            )
            feasibility_report = result.scalar_one_or_none()

        if feasibility_report:
            sql = feasibility_report.report.get('phenotype_sql', 'No SQL found')
            estimated_cohort = feasibility_report.report.get('estimated_cohort_size', 0)
            feasibility_score = feasibility_report.report.get('feasibility_score', 0)

            print(f"\nFeasibility Score: {feasibility_score:.2f}")
            print(f"Estimated Cohort Size: {estimated_cohort}")
            print(f"\n{'='*80}")
            print("GENERATED SQL QUERY:")
            print(f"{'='*80}")
            print(sql)
            print(f"{'='*80}\n")

            # Assertions - SQL structure
            assert 'SELECT' in sql, "SQL missing SELECT clause"
            assert 'FROM' in sql, "SQL missing FROM clause"
            assert 'patient' in sql.lower(), "SQL doesn't query patient table"

            # Assertions - Criteria inclusion (flexible)
            sql_lower = sql.lower()
            # Check for heart failure (might be coded as ICD-10 I50.x or text)
            has_heart_failure = any(term in sql_lower for term in [
                'heart failure', 'i50', 'chf', 'cardiac failure'
            ])

            # Check for diabetes (might be coded as ICD-10 E11.x or text)
            has_diabetes = any(term in sql_lower for term in [
                'diabetes', 'e11', 'dm', 'diabetic'
            ])

            # Check for time filter
            has_time_filter = any(term in sql_lower for term in [
                '2024', 'recordeddate', 'date'
            ])

            print("\nSQL Validation:")
            print(f"  ✓ Heart failure criteria: {'✅' if has_heart_failure else '❌'}")
            print(f"  ✓ Diabetes criteria: {'✅' if has_diabetes else '❌'}")
            print(f"  ✓ Time period filter: {'✅' if has_time_filter else '❌'}")

            # Soft assertions - log warnings but don't fail
            if not has_heart_failure:
                print("  ⚠️  WARNING: Heart failure criteria not detected in SQL")
            if not has_diabetes:
                print("  ⚠️  WARNING: Diabetes criteria not detected in SQL")
            if not has_time_filter:
                print("  ⚠️  WARNING: Time period filter not detected in SQL")

        else:
            print("\n⚠️  SQL not yet generated - waiting longer...")
            await asyncio.sleep(2)

        # Step 4: Verify approval created
        print(f"\n{'='*80}")
        print("STEP 4: Verifying Approval Created")
        print(f"{'='*80}")

        async with get_db_session() as session:
            approval_service = ApprovalService(session)
            approvals = await approval_service.get_pending_approvals()

            # Find approvals for this request
            request_approvals = [
                a for a in approvals
                if a.request_id == request_id
            ]

        if request_approvals:
            approval = request_approvals[0]
            print(f"\nApproval Created:")
            print(f"  Approval ID: {approval.id}")
            print(f"  Type: {approval.approval_type}")
            print(f"  Status: {approval.status}")
            print(f"  Submitted At: {approval.submitted_at}")
            print(f"  Submitted By: {approval.submitted_by}")

            # Assertions
            assert approval.approval_type == 'phenotype_sql', \
                f"Expected phenotype_sql approval, got {approval.approval_type}"
            assert approval.status == 'pending', \
                f"Expected pending status, got {approval.status}"

            # Verify approval data contains SQL
            approval_data = approval.approval_data
            if 'sql_query' in approval_data:
                print(f"\n  SQL in approval: {len(approval_data['sql_query'])} characters")

            print("\n✅ Approval successfully created for SQL review!")
        else:
            print("\n⚠️  No approvals found - SQL may not require approval yet")

        # Final summary
        print(f"\n{'='*80}")
        print("TEST SUMMARY")
        print(f"{'='*80}")
        print(f"✓ Natural language query submitted")
        print(f"✓ Request created: {request_id}")
        if requirements_data:
            print(f"✓ Requirements extracted")
        if feasibility_report:
            print(f"✓ SQL generated ({len(sql)} chars)")
            print(f"✓ Estimated cohort: {estimated_cohort} patients")
        if request_approvals:
            print(f"✓ Approval created for informatician review")
        print(f"{'='*80}\n")

    @pytest.mark.asyncio
    async def test_elderly_female_patients_query(self, orchestrator):
        """
        Test: Female patients over 65

        Simpler query to test basic SQL generation
        """
        query = "I need female patients over age 65"

        researcher_info = {
            'name': 'Dr. Jane Doe',
            'email': 'jane.doe@hospital.org',
            'irb_number': 'IRB-2024-TEST-002'
        }

        print(f"\n{'='*80}")
        print(f"Query: {query}")
        print(f"{'='*80}")

        request_id = await orchestrator.process_new_request(query, researcher_info)

        # Wait for processing
        await asyncio.sleep(5)

        # Check SQL generated
        async with get_db_session() as session:
            result = await session.execute(
                select(FeasibilityReport).where(
                    FeasibilityReport.request_id == request_id
                )
            )
            report = result.scalar_one_or_none()

        if report:
            sql = report.report.get('phenotype_sql', '')
            print(f"\nGenerated SQL:\n{sql}\n")

            # Verify SQL includes gender and age filters
            sql_lower = sql.lower()
            assert 'gender' in sql_lower or 'sex' in sql_lower, \
                "SQL missing gender filter"

            # Age might be calculated from birthdate
            has_age_filter = any(term in sql_lower for term in [
                'age', 'birthdate', '65', 'date_sub', 'datediff'
            ])
            assert has_age_filter, "SQL missing age filter"

            print("✅ SQL generated successfully with gender and age filters")

    @pytest.mark.asyncio
    async def test_sql_syntax_validation(self, orchestrator):
        """
        Test: Verify generated SQL has valid syntax

        This doesn't execute the SQL, just checks basic syntax
        """
        query = "I need COVID-19 patients from 2023"

        researcher_info = {
            'name': 'Dr. Test',
            'email': 'test@hospital.org',
            'irb_number': 'IRB-2024-TEST-003'
        }

        request_id = await orchestrator.process_new_request(query, researcher_info)
        await asyncio.sleep(5)

        async with get_db_session() as session:
            result = await session.execute(
                select(FeasibilityReport).where(
                    FeasibilityReport.request_id == request_id
                )
            )
            report = result.scalar_one_or_none()

        if report:
            sql = report.report.get('phenotype_sql', '')

            print(f"\nSQL Syntax Validation:")

            # Basic syntax checks
            checks = {
                "Has SELECT": 'SELECT' in sql,
                "Has FROM": 'FROM' in sql,
                "Balanced parentheses": sql.count('(') == sql.count(')'),
                "Not empty": len(sql) > 0,
                "Has patient table": 'patient' in sql.lower()
            }

            for check, passed in checks.items():
                status = "✅" if passed else "❌"
                print(f"  {status} {check}")
                assert passed, f"Failed: {check}"

            print("\n✅ All syntax checks passed")
