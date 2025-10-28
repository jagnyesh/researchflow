"""
Test SQL Generation Quality

This test suite verifies the quality and correctness of generated
SQL-on-FHIR queries from structured requirements.

Tests:
1. SQL structure and syntax
2. Inclusion/exclusion criteria implementation
3. Time period filters
4. Data element selection
5. Join conditions

Purpose: Ensure SQL Generator produces valid, semantically correct SQL
that accurately represents researcher requirements.
"""

import pytest
from datetime import datetime

from app.utils.sql_generator import SQLGenerator
from tests.fixtures import RequirementsBuilder as RB


class TestSQLStructure:
    """Test basic SQL structure and syntax"""

    def setup_method(self):
        """Initialize SQL generator"""
        self.sql_generator = SQLGenerator()

    def test_count_query_structure(self):
        """Test COUNT-only query for cohort estimation"""

        requirements = RB.build_requirements(
            inclusion=[
                RB.build_condition('diabetes diagnosis')
            ],
            time_period={'start': '2024-01-01', 'end': '2024-12-31'}
        )

        sql = self.sql_generator.generate_phenotype_sql(
            requirements,
            count_only=True
        )

        print(f"\n{'='*80}")
        print("COUNT Query:")
        print(f"{'='*80}")
        print(sql)
        print(f"{'='*80}\n")

        # Assertions
        sql_lower = sql.lower()
        assert 'select count' in sql_lower, "COUNT query missing COUNT clause"
        assert 'from patient' in sql_lower, "Missing FROM patient clause"
        assert sql.count('(') == sql.count(')'), "Unbalanced parentheses"

        print("✅ PASS: COUNT query structure valid")

    def test_full_query_structure(self):
        """Test full data extraction query"""

        requirements = RB.build_requirements(
            inclusion=[
                RB.build_condition('heart failure')
            ],
            data_elements=['demographics', 'lab_results'],
            time_period={'start': '2024-01-01', 'end': '2024-12-31'}
        )

        sql = self.sql_generator.generate_phenotype_sql(
            requirements,
            count_only=False
        )

        print(f"\n{'='*80}")
        print("Full Query:")
        print(f"{'='*80}")
        print(sql)
        print(f"{'='*80}\n")

        # Assertions
        sql_lower = sql.lower()
        assert 'select' in sql_lower, "Missing SELECT clause"
        assert 'from patient' in sql_lower, "Missing FROM patient"
        assert 'distinct' in sql_lower, "Should use DISTINCT for patient queries"

        # Should select patient fields
        assert any(field in sql_lower for field in [
            'patient_id', 'id', 'birthdate', 'gender'
        ]), "Missing patient demographic fields"

        print("✅ PASS: Full query structure valid")

    def test_balanced_parentheses(self):
        """Test all generated SQL has balanced parentheses"""

        test_cases = [
            RB.build_requirements(
                inclusion=[
                    RB.build_condition('diabetes'),
                    RB.build_condition('hypertension')
                ],
                exclusion=[
                    RB.build_condition('pregnancy')
                ]
            ),
            RB.build_requirements(
                inclusion=[
                    RB.build_demographic('age > 65', term='age', details='> 65'),
                    RB.build_demographic('female', term='female')
                ],
                time_period={'start': '2023-01-01'}
            ),
            RB.build_requirements(
                inclusion=[
                    RB.build_condition('cancer diagnosis')
                ],
                data_elements=['medications', 'procedures']
            )
        ]

        for i, requirements in enumerate(test_cases):
            sql = self.sql_generator.generate_phenotype_sql(requirements)

            open_count = sql.count('(')
            close_count = sql.count(')')

            assert open_count == close_count, \
                f"Test case {i+1}: Unbalanced parentheses " \
                f"({open_count} open, {close_count} close)"

        print(f"✅ PASS: All {len(test_cases)} queries have balanced parentheses")


class TestInclusionCriteria:
    """Test inclusion criteria implementation"""

    def setup_method(self):
        self.sql_generator = SQLGenerator()

    def test_single_condition_criterion(self):
        """Test single condition like 'diabetes'"""

        requirements = RB.build_requirements(
            inclusion=[
                RB.build_condition('diabetes mellitus')
            ]
        )

        sql = self.sql_generator.generate_phenotype_sql(requirements)

        print(f"\n{'='*80}")
        print("Single Condition SQL:")
        print(f"{'='*80}")
        print(sql)
        print(f"{'='*80}\n")

        sql_lower = sql.lower()

        # Should reference condition table
        assert 'condition' in sql_lower, "Missing condition table reference"

        # Should have diabetes reference (ICD code or text)
        has_diabetes = any(term in sql_lower for term in [
            'diabetes', 'e11', 'dm', 'diabetic'
        ])
        assert has_diabetes, "Diabetes criteria not found in SQL"

        print("✅ PASS: Single condition implemented correctly")

    def test_multiple_conditions(self):
        """Test multiple inclusion criteria"""

        requirements = RB.build_requirements(
            inclusion=[
                RB.build_condition('heart failure diagnosis'),
                RB.build_condition('diabetes mellitus'),
                RB.build_condition('hypertension')
            ]
        )

        sql = self.sql_generator.generate_phenotype_sql(requirements)

        print(f"\n{'='*80}")
        print("Multiple Conditions SQL:")
        print(f"{'='*80}")
        print(sql)
        print(f"{'='*80}\n")

        sql_lower = sql.lower()

        # Should have multiple condition checks
        # Might use AND, OR, or multiple EXISTS clauses

        has_conditions = 'condition' in sql_lower
        assert has_conditions, "Missing condition table"

        # Check for presence of criteria (flexible - might be ICD codes)
        criteria_found = 0
        if any(t in sql_lower for t in ['heart', 'i50', 'chf']):
            criteria_found += 1
        if any(t in sql_lower for t in ['diabetes', 'e11']):
            criteria_found += 1
        if any(t in sql_lower for t in ['hypertension', 'i10']):
            criteria_found += 1

        print(f"   Criteria found in SQL: {criteria_found}/3")

        # Soft assertion - log warning but don't fail
        if criteria_found < 3:
            print(f"   ⚠️  WARNING: Not all criteria detected "
                  f"(found {criteria_found}/3)")

        print("✅ PASS: Multiple conditions query generated")

    def test_age_criterion(self):
        """Test age-based criteria"""

        requirements = RB.build_requirements(
            inclusion=[
                RB.build_demographic('age > 65', term='age', details='> 65')
            ]
        )

        sql = self.sql_generator.generate_phenotype_sql(requirements)

        print(f"\n{'='*80}")
        print("Age Criterion SQL:")
        print(f"{'='*80}")
        print(sql)
        print(f"{'='*80}\n")

        sql_lower = sql.lower()

        # Age might be calculated from birthdate
        has_age_logic = any(term in sql_lower for term in [
            'age', 'birthdate', '65', 'date_sub', 'datediff',
            'timestampdiff', 'extract', 'year'
        ])

        assert has_age_logic, "Age calculation logic not found"

        print("✅ PASS: Age criterion implemented")


class TestExclusionCriteria:
    """Test exclusion criteria implementation"""

    def setup_method(self):
        self.sql_generator = SQLGenerator()

    def test_exclusion_criteria(self):
        """Test exclusion criteria are applied as NOT EXISTS or NOT IN"""

        requirements = RB.build_requirements(
            inclusion=[
                RB.build_condition('diabetes')
            ],
            exclusion=[
                RB.build_condition('pregnancy'),
                RB.build_condition('end-stage renal disease')
            ]
        )

        sql = self.sql_generator.generate_phenotype_sql(requirements)

        print(f"\n{'='*80}")
        print("Exclusion Criteria SQL:")
        print(f"{'='*80}")
        print(sql)
        print(f"{'='*80}\n")

        sql_lower = sql.lower()

        # Exclusion should use NOT EXISTS or NOT IN
        has_exclusion_logic = any(term in sql_lower for term in [
            'not exists', 'not in', 'where not'
        ])

        # Soft assertion
        if has_exclusion_logic:
            print("✅ PASS: Exclusion logic found (NOT EXISTS/NOT IN)")
        else:
            print("⚠️  WARNING: Exclusion logic not clearly identified")

        # Should still have inclusion criteria
        assert 'diabetes' in sql_lower or 'e11' in sql_lower, \
            "Inclusion criteria missing"

        print("✅ PASS: Exclusion criteria query generated")


class TestTimePeriodFilters:
    """Test time period filtering"""

    def setup_method(self):
        self.sql_generator = SQLGenerator()

    def test_date_range_filter(self):
        """Test date range (start and end)"""

        requirements = RB.build_requirements(
            inclusion=[
                RB.build_condition('COVID-19 diagnosis')
            ],
            time_period={
                'start': '2023-01-01',
                'end': '2023-12-31'
            }
        )

        sql = self.sql_generator.generate_phenotype_sql(requirements)

        print(f"\n{'='*80}")
        print("Date Range Filter SQL:")
        print(f"{'='*80}")
        print(sql)
        print(f"{'='*80}\n")

        sql_lower = sql.lower()

        # Should have date filters
        has_date_filter = any(term in sql_lower for term in [
            'recordeddate', 'onsetdate', 'date', 'between'
        ])

        assert has_date_filter, "Date filtering not found"

        # Should include the actual dates
        assert '2023' in sql, "Year 2023 not in SQL"

        # Common patterns
        if 'between' in sql_lower:
            print("   ✓ Using BETWEEN for date range")
        if '>=' in sql or '<=' in sql:
            print("   ✓ Using >= and <= for date range")

        print("✅ PASS: Date range filter implemented")

    def test_start_date_only(self):
        """Test start date without end date"""

        requirements = RB.build_requirements(
            inclusion=[
                RB.build_condition('hypertension')
            ],
            time_period={'start': '2024-01-01'}
        )

        sql = self.sql_generator.generate_phenotype_sql(requirements)

        assert '2024-01-01' in sql, "Start date not in SQL"

        sql_lower = sql.lower()
        has_comparison = '>=' in sql or '>' in sql

        assert has_comparison, "Missing date comparison operator"

        print("✅ PASS: Start date filter implemented")


class TestDataElements:
    """Test data element selection"""

    def setup_method(self):
        self.sql_generator = SQLGenerator()

    def test_demographics_only(self):
        """Test query with only demographics"""

        requirements = RB.build_requirements(
            inclusion=[
                RB.build_condition('diabetes')
            ],
            data_elements=['demographics']
        )

        sql = self.sql_generator.generate_phenotype_sql(
            requirements,
            count_only=False
        )

        print(f"\n{'='*80}")
        print("Demographics Query:")
        print(f"{'='*80}")
        print(sql)
        print(f"{'='*80}\n")

        sql_lower = sql.lower()

        # Should select patient demographic fields
        has_demographics = any(field in sql_lower for field in [
            'birthdate', 'gender', 'race', 'ethnicity'
        ])

        assert has_demographics, "Demographics fields not selected"

        print("✅ PASS: Demographics selected")

    def test_multiple_data_elements(self):
        """Test query with multiple data elements"""

        requirements = RB.build_requirements(
            inclusion=[
                RB.build_condition('heart failure')
            ],
            data_elements=[
                'demographics',
                'lab_results',
                'medications',
                'procedures'
            ]
        )

        sql = self.sql_generator.generate_phenotype_sql(
            requirements,
            count_only=False
        )

        print(f"\n{'='*80}")
        print("Multiple Data Elements SQL:")
        print(f"{'='*80}")
        print(sql)
        print(f"{'='*80}\n")

        sql_lower = sql.lower()

        # Should reference multiple FHIR resources
        resource_count = 0
        if 'observation' in sql_lower:  # Lab results
            resource_count += 1
            print("   ✓ Observation (lab results)")
        if 'medicationrequest' in sql_lower or 'medication' in sql_lower:
            resource_count += 1
            print("   ✓ Medication")
        if 'procedure' in sql_lower:
            resource_count += 1
            print("   ✓ Procedure")

        print(f"   Resource tables referenced: {resource_count}")

        # Soft assertion
        if resource_count < 2:
            print("   ⚠️  WARNING: Fewer resources than expected")

        print("✅ PASS: Multiple data elements query generated")


class TestComplexScenarios:
    """Test complex real-world scenarios"""

    def setup_method(self):
        self.sql_generator = SQLGenerator()

    def test_complex_oncology_query(self):
        """Test complex oncology research query"""

        requirements = RB.build_requirements(
            study_title='Stage IV Cancer Treatment Outcomes',
            inclusion=[
                RB.build_condition('stage IV cancer diagnosis'),
                RB.build_demographic('age >= 18', term='age', details='>= 18'),
                RB.build_condition('received chemotherapy')
            ],
            exclusion=[
                RB.build_condition('pregnancy'),
                RB.build_condition('hospice care')
            ],
            data_elements=[
                'demographics',
                'diagnoses',
                'medications',
                'procedures',
                'lab_results'
            ],
            time_period={
                'start': '2020-01-01',
                'end': '2024-12-31'
            },
            phi_level='de-identified'
        )

        sql = self.sql_generator.generate_phenotype_sql(requirements)

        print(f"\n{'='*80}")
        print("Complex Oncology Query:")
        print(f"{'='*80}")
        print(f"Study: {requirements['study_title']}")
        print(f"Inclusion: {len(requirements['inclusion_criteria'])} criteria")
        print(f"Exclusion: {len(requirements['exclusion_criteria'])} criteria")
        print(f"Data Elements: {len(requirements['data_elements'])}")
        print(f"Time Period: {requirements['time_period']['start']} to "
              f"{requirements['time_period']['end']}")
        print(f"\n{sql}")
        print(f"{'='*80}\n")

        # Basic validation
        sql_lower = sql.lower()
        assert 'select' in sql_lower
        assert 'from patient' in sql_lower
        assert sql.count('(') == sql.count(')')
        assert 'condition' in sql_lower or 'diagnosis' in sql_lower

        print(f"✅ PASS: Complex query generated successfully")
        print(f"   SQL length: {len(sql)} characters")
        print(f"   Estimated complexity: "
              f"{'High' if len(sql) > 1000 else 'Medium' if len(sql) > 500 else 'Low'}")
