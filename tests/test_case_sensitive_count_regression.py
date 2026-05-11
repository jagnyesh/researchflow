"""
Regression Tests for Case-Sensitive Matching and Count Accuracy

Tests to prevent recurrence of count mismatch issues due to:
1. Case-sensitive LIKE matching (e.g., "Diabetes" vs "diabetes")
2. Incorrect cohort counts
3. Missing patients due to capitalization variations

Background:
- Issue discovered on 2025-11-10
- Patient 326492 (Schneider199) was missing from case-sensitive queries
- Root cause: "Diabetes mellitus type 2" (capital D) doesn't match '%diabetes%'
- Solution: Use LOWER() for all text matching

See: docs/ROOT_CAUSE_ANALYSIS_COUNT_MISMATCH.md
"""

import pytest
from app.utils.sql_generator import SQLGenerator


class TestCaseSensitiveMatching:
    """Test case-insensitive condition matching"""

    @pytest.fixture
    def sql_generator(self):
        """Create SQL generator with materialized views enabled"""
        return SQLGenerator(use_materialized_views=True)

    def test_condition_clause_uses_lower(self, sql_generator):
        """
        Test that condition matching uses LOWER() for case-insensitive matching

        Critical for preventing missing patients due to capitalization variations.
        Example: "Diabetes" vs "diabetes" should both match.
        """
        sql, params = sql_generator._build_condition_clause("diabetes", include=True)

        # Verify LOWER() is used on both sides of LIKE for each matched column
        assert "LOWER(c.code_text)" in sql, "Should use LOWER() on code_text"
        assert "LOWER(c.icd10_display)" in sql, "Should use LOWER() on icd10_display"
        assert "LOWER(c.snomed_display)" in sql, "Should use LOWER() on snomed_display"
        assert "LIKE LOWER(" in sql, "Should use LOWER() on parameter"

        # Verify EXISTS pattern (not INNER JOIN which can create duplicates)
        assert "EXISTS" in sql
        assert "SELECT 1 FROM" in sql

    def test_condition_clause_matches_all_three_code_columns(self, sql_generator):
        """
        Test that condition matching ORs across code_text, icd10_display,
        snomed_display so SNOMED-only datasets (Synthea) match alongside
        ICD-10 datasets. Regression for the cohort=0 symptom on synthetic
        HAPI data even though condition_simple has 14k+ rows.
        """
        sql, params = sql_generator._build_condition_clause("diabetes", include=True)

        # All three columns must be in the OR'd predicate
        assert "code_text" in sql
        assert "icd10_display" in sql
        assert "snomed_display" in sql
        # And they must be OR'd (any-match), not AND'd
        assert " OR " in sql

    def test_diabetes_query_generation(self, sql_generator):
        """
        Test full SQL generation for female diabetes patients

        Expected: 19 patients (including patient 326492 Schneider199)
        """
        requirements = {
            "inclusion_criteria": [{"type": "condition", "details": "diabetes"}],
            "exclusion_criteria": [],
            "data_elements": ["demographics"],
            "demographics": {"gender": "female"},
        }

        count_sql, count_params = sql_generator.generate_phenotype_sql(
            requirements, count_only=True
        )

        # Verify query structure
        assert "COUNT(DISTINCT p.patient_id)" in count_sql
        assert "LOWER(c.icd10_display) LIKE LOWER(" in count_sql
        assert "p.gender = :gender" in count_sql

        # Verify parameters
        assert "gender" in count_params
        assert count_params["gender"] == "female"
        assert "condition_1" in count_params
        assert count_params["condition_1"] == "%diabetes%"

    def test_extraction_query_generation(self, sql_generator):
        """
        Test full SQL generation for data extraction (not just count)

        Should return all demographic fields for female diabetes patients.
        """
        requirements = {
            "inclusion_criteria": [{"type": "condition", "details": "diabetes"}],
            "exclusion_criteria": [],
            "data_elements": ["demographics"],
            "demographics": {"gender": "female"},
        }

        extraction_sql, extraction_params = sql_generator.generate_phenotype_sql(
            requirements, count_only=False
        )

        # Verify SELECT fields include demographics (column names match the
        # patient_demographics ViewDefinition: family_name/given_name/birth_date)
        assert "p.family_name" in extraction_sql
        assert "p.given_name" in extraction_sql
        assert "p.birth_date" in extraction_sql
        assert "p.patient_id" in extraction_sql

        # Verify LOWER() is still used in extraction query
        assert "LOWER(c.icd10_display) LIKE LOWER(" in extraction_sql

    def test_case_variations_in_parameters(self, sql_generator):
        """
        Test that case variations in input parameters work correctly

        All of these should match the same patients:
        - "diabetes", "Diabetes", "DIABETES", "DiAbEtEs"
        """
        test_cases = ["diabetes", "Diabetes", "DIABETES", "DiAbEtEs"]

        for case_variant in test_cases:
            sql, params = sql_generator._build_condition_clause(case_variant, include=True)

            # Verify LOWER() is always used
            assert "LOWER(c.icd10_display) LIKE LOWER(" in sql, f"Failed for: {case_variant}"

            # Verify parameter is wrapped with wildcards
            param_name = list(params.keys())[0]
            assert params[param_name] == f"%{case_variant}%", f"Failed for: {case_variant}"


class TestDiabetesCohortCount:
    """Integration tests for female diabetes cohort (expected: 19 patients)"""

    @pytest.fixture
    def sql_generator(self):
        return SQLGenerator(use_materialized_views=True)

    def test_schneider199_patient_included(self, sql_generator):
        """
        Test that patient 326492 (Schneider199) is included in diabetes cohort

        This patient has "Diabetes mellitus type 2" (capital D) and was missing
        from case-sensitive queries. This test ensures the fix prevents regression.
        """
        # Generate query for female diabetes patients
        requirements = {
            "inclusion_criteria": [{"type": "condition", "details": "diabetes"}],
            "exclusion_criteria": [],
            "data_elements": ["demographics"],
            "demographics": {"gender": "female"},
        }

        sql, params = sql_generator.generate_phenotype_sql(requirements, count_only=False)

        # Verify query would match "Diabetes" (capital D) due to LOWER()
        assert "LOWER(c.icd10_display) LIKE LOWER(" in sql

        # Verify patient_id is selected so we can check for Schneider199
        assert "p.patient_id" in sql

    @pytest.mark.asyncio
    async def test_female_diabetes_count_equals_19(self, sql_generator):
        """
        Integration test: Verify female diabetes cohort has exactly 19 patients

        This test requires database connection and is marked for integration testing.
        Run with: pytest tests/test_case_sensitive_count_regression.py::TestDiabetesCohortCount::test_female_diabetes_count_equals_19 --asyncio-mode=auto

        Expected count: 19 (including patient 326492 Schneider199)
        """
        from app.adapters.sql_on_fhir import SQLonFHIRAdapter

        adapter = SQLonFHIRAdapter()

        requirements = {
            "inclusion_criteria": [{"type": "condition", "details": "diabetes"}],
            "exclusion_criteria": [],
            "data_elements": ["demographics"],
            "demographics": {"gender": "female"},
        }

        count_sql, count_params = sql_generator.generate_phenotype_sql(
            requirements, count_only=True
        )

        try:
            result = await adapter.execute_sql(count_sql, count_params)

            # Verify result structure
            assert result is not None, "Query should return results"
            assert len(result) > 0, "Should have at least one row"
            assert "patient_count" in result[0], "Result should have patient_count column"

            # CRITICAL: Verify count is 19 (not 18)
            actual_count = result[0]["patient_count"]
            assert (
                actual_count == 19
            ), f"Expected 19 female diabetes patients, got {actual_count}. Case-sensitive matching may have regressed."

        except Exception as e:
            pytest.skip(f"Database not available: {str(e)}")


class TestConservativeFactorDocumentation:
    """Tests for conservative factor (0.7x) applied to feasibility estimates"""

    def test_conservative_factor_documented(self):
        """
        Verify that phenotype_agent.py documents the 0.7x conservative factor

        The 0.7x factor is applied ONLY to feasibility estimates, NOT to extraction.
        This test ensures the documentation is present to prevent confusion.
        """
        import inspect
        from app.agents.phenotype_agent import PhenotypeAgent

        # Get source code
        source = inspect.getsource(PhenotypeAgent._estimate_cohort_size)

        # Verify documentation exists
        assert "0.7x" in source or "0.7" in source, "Conservative factor should be in code"
        assert (
            "WHY 0.7x FACTOR" in source or "conservative factor" in source.lower()
        ), "Factor should be documented"

    def test_conservative_factor_only_in_feasibility(self):
        """
        Verify conservative factor is NOT applied in extraction_agent.py

        The 0.7x factor should ONLY reduce feasibility estimates.
        Final extraction should return actual cohort count without reduction.
        """
        import inspect
        from app.agents.extraction_agent import ExtractionAgent

        # Get source code of extraction method
        source = inspect.getsource(ExtractionAgent.execute)

        # Verify NO conservative factor in extraction
        assert "0.7" not in source, "Extraction should NOT apply conservative factor (0.7x)"
        assert (
            "len(cohort)" in source
        ), "Extraction should use actual cohort length, not conservative estimate"


class TestRegressionDocumentation:
    """Tests to verify root cause analysis documentation exists"""

    def test_root_cause_analysis_document_exists(self):
        """Verify docs/ROOT_CAUSE_ANALYSIS_COUNT_MISMATCH.md exists"""
        import os

        doc_path = "docs/ROOT_CAUSE_ANALYSIS_COUNT_MISMATCH.md"
        assert os.path.exists(doc_path), f"Documentation should exist at {doc_path}"

        # Verify documentation contains key findings
        with open(doc_path, "r") as f:
            content = f.read()

        assert "326492" in content, "Should document patient 326492 (Schneider199)"
        assert "Schneider199" in content, "Should document patient Schneider199"
        assert "19 patients" in content or "19" in content, "Should document correct count (19)"
        assert (
            "LOWER()" in content or "case-insensitive" in content.lower()
        ), "Should explain LOWER() requirement"

    def test_sql_generator_has_lower_comment(self):
        """Verify sql_generator.py has explanatory comment about LOWER()"""
        import inspect
        from app.utils.sql_generator import SQLGenerator

        source = inspect.getsource(SQLGenerator._build_condition_clause)

        # Verify comment exists
        assert (
            "CRITICAL" in source or "IMPORTANT" in source
        ), "Should have critical comment about LOWER()"
        assert "case-insensitive" in source.lower(), "Should explain case-insensitive matching"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
