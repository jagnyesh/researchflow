"""
Regression tests for issue #21: phenotype SQL generator drops demographic
predicates from structured criteria.

Pins three behaviors:
1. Dispatcher accepts both "demographic" (singular, what the LLM extractor
   and RequirementsBuilder produce) and "demographics" (plural).
2. Age comparison uses p.dob (the column the materialized view exposes),
   not p.birthdate.
3. Combined demographic + diagnosis criteria produce a WHERE clause with
   ALL predicates, not just the diagnosis one.
"""

import pytest

from app.utils.sql_generator import SQLGenerator
from tests.fixtures import RequirementsBuilder as RB


@pytest.fixture
def gen():
    return SQLGenerator(use_materialized_views=True)


class TestDemographicPredicatesEmitted:
    """Issue #21: structured demographic criteria must reach the WHERE clause."""

    def test_gender_male_emits_gender_predicate(self, gen):
        reqs = RB.build_requirements(inclusion=[RB.build_demographic("Male patients", term="male")])
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert "p.gender" in sql, f"missing gender predicate; sql=\n{sql}"
        assert "male" in params.values(), f"gender param not bound; params={params}"

    def test_gender_female_emits_gender_predicate(self, gen):
        reqs = RB.build_requirements(
            inclusion=[RB.build_demographic("Female patients", term="female")]
        )
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert "p.gender" in sql, f"missing gender predicate; sql=\n{sql}"
        assert "female" in params.values(), f"gender param not bound; params={params}"

    def test_age_greater_than_emits_age_predicate_against_dob(self, gen):
        reqs = RB.build_requirements(
            inclusion=[RB.build_demographic("Age > 18", term="age", details="> 18")]
        )
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert (
            "p.dob" in sql
        ), f"age clause must reference p.dob (the MV column), not p.birthdate; sql=\n{sql}"
        assert (
            "p.birthdate" not in sql
        ), f"p.birthdate doesn't exist in patient_demographics MV; sql=\n{sql}"
        assert 18 in params.values(), f"age param not bound; params={params}"

    def test_combined_gender_age_diagnosis_emits_all_three_predicates(self, gen):
        """The exact case from issue #21: 'male diabetics over 18'."""
        reqs = RB.build_requirements(
            inclusion=[
                RB.build_demographic("Male patients", term="male"),
                RB.build_demographic("Age > 18", term="age", details="> 18"),
                RB.build_condition("diabetes"),
            ]
        )
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert "p.gender" in sql, f"gender predicate missing; sql=\n{sql}"
        assert "p.dob" in sql, f"age predicate missing; sql=\n{sql}"
        assert "condition_simple" in sql, f"diagnosis predicate missing; sql=\n{sql}"
        assert (
            sql.count("AND") >= 2
        ), f"expected at least 2 AND-joined predicates in WHERE; sql=\n{sql}"


class TestDemographicTypeStringTolerance:
    """Dispatcher must accept both 'demographic' (LLM output) and 'demographics'."""

    @pytest.mark.parametrize(
        "details,expected_op,expected_age",
        [
            ("> 18", ">", 18),
            ("greater than 18", ">", 18),
            ("greater than 18 years", ">", 18),
            ("above 18", ">", 18),
            ("over 18", ">", 18),
            ("< 65", "<", 65),
            ("less than 65", "<", 65),
            ("below 65", "<", 65),
            ("under 65", "<", 65),
        ],
    )
    def test_age_clause_handles_natural_language_operators(
        self, gen, details, expected_op, expected_age
    ):
        """LLM extractor emits 'greater than 18 years' style details, not '> 18'."""
        reqs = {
            "inclusion_criteria": [
                {
                    "description": f"Age {details}",
                    "concepts": [{"type": "demographic", "term": "age", "details": details}],
                    "codes": [],
                }
            ],
            "exclusion_criteria": [],
            "data_elements": [],
            "time_period": {},
        }
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert "p.dob" in sql, f"age clause missing for details='{details}'; sql=\n{sql}"
        assert (
            expected_op in sql
        ), f"expected operator '{expected_op}' missing for details='{details}'; sql=\n{sql}"
        assert (
            expected_age in params.values()
        ), f"expected age value {expected_age} missing for details='{details}'; params={params}"

    @pytest.mark.parametrize("concept_type", ["demographic", "demographics"])
    def test_dispatcher_accepts_both_singular_and_plural(self, gen, concept_type):
        reqs = {
            "inclusion_criteria": [
                {
                    "description": "Male patients",
                    "concepts": [{"type": concept_type, "term": "male"}],
                    "codes": [],
                }
            ],
            "exclusion_criteria": [],
            "data_elements": [],
            "time_period": {},
        }
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert (
            "p.gender" in sql
        ), f"type='{concept_type}' should produce gender predicate; sql=\n{sql}"
