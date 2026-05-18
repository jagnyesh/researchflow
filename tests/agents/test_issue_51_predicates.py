"""
Issue #51 regression coverage. The deterministic tests are the load-bearing
regression gate — they use RequirementsBuilder to produce the expected
criterion shape and verify SQL generation handles it correctly. The
LLM-gated tests are diagnostic — they verify the LLM prompt produces the
expected shape at time of writing. Future model behavior shifts may flake
these tests; when they fail, investigate whether the LLM output shape
changed rather than treating it as a code regression.

The active bug fixed by `fix(#51): _parse_age_details range support` is
narrower than the issue body framed it: only AGE-RANGE phrasings (the
LLM's canonical "between X and Y" format per _MEDICAL_CONCEPTS_SYSTEM_PROMPT)
were dropped. Single-comparison ages (`> 18`, `over 65`) were always
handled correctly post-Sprint-6.2 #21. Phase 2 stress test confirmed
28% (7/25) pre-fix failure rate, 0% (0/25) post-fix.

Verdict layer per pre-committed plan: (iii) — Layer 2 fix in
`_parse_age_details` + `_build_demographic_clause`. Latent age-first
early-return filed as Sprint 6.5c candidate (#82), NOT bundled here.
"""

import pytest

from app.utils.sql_generator import SQLGenerator
from tests.fixtures import RequirementsBuilder as RB


@pytest.fixture
def gen():
    return SQLGenerator(use_materialized_views=True)


class TestIssue51DeterministicRegression:
    """Load-bearing regression gate. Uses RequirementsBuilder to construct
    the canonical concept shape, bypassing the LLM. These MUST always pass
    after the fix lands. A failure here is a real code regression.
    """

    def test_age_between_range_emits_between_predicate(self, gen):
        """The exact failure shape Phase 2 stress test surfaced: an age
        concept with `details='between 40 and 65'`. Pre-fix, this returned
        ("", {}) from _parse_age_details and silently dropped the age
        predicate. Post-fix, emits an inclusive BETWEEN SQL clause.
        """
        reqs = RB.build_requirements(
            inclusion=[RB.build_demographic("Age 40-65", term="age", details="between 40 and 65")]
        )
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert "BETWEEN" in sql, f"missing BETWEEN predicate; sql=\n{sql}"
        assert "p.birth_date::date" in sql, f"age clause must reference p.birth_date; sql=\n{sql}"
        assert 40 in params.values(), f"age_lo param not bound; params={params}"
        assert 65 in params.values(), f"age_hi param not bound; params={params}"

    def test_age_between_range_with_trailing_comment(self, gen):
        """The LLM sometimes emits trailing commentary after the numeric range
        (e.g., 'between 20 and 29 (in their 20s)'). The parser's partial-match
        regex tolerates this by anchoring on the canonical "between X and Y"
        substring and ignoring trailing chars.
        """
        reqs = RB.build_requirements(
            inclusion=[
                RB.build_demographic(
                    "Age 20s", term="age", details="between 20 and 29 (in their 20s)"
                )
            ]
        )
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert "BETWEEN" in sql, f"missing BETWEEN predicate; sql=\n{sql}"
        assert (
            20 in params.values() and 29 in params.values()
        ), f"range bounds not bound correctly; params={params}"

    def test_male_diabetic_over_18_produces_gender_age_diagnosis_predicates(self, gen):
        """The exact #51 issue-body input shape, using the comparison-op path.
        This always worked post-#21 (verified) — pinning the regression so
        future refactors don't break it.
        """
        reqs = RB.build_requirements(
            inclusion=[
                RB.build_demographic("Male patients", term="gender", details="male"),
                RB.build_demographic("Age > 18", term="age", details="> 18"),
                RB.build_condition("diabetes"),
            ]
        )
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert "p.gender" in sql, f"gender predicate missing; sql=\n{sql}"
        assert "p.birth_date" in sql, f"age predicate missing; sql=\n{sql}"
        assert "condition_simple" in sql, f"diagnosis predicate missing; sql=\n{sql}"
        assert "male" in params.values(), f"gender param not bound; params={params}"

    def test_female_hypertension_over_65_produces_gender_age_diagnosis_predicates(self, gen):
        """Second test input from backlog acceptance criteria."""
        reqs = RB.build_requirements(
            inclusion=[
                RB.build_demographic("Female patients", term="gender", details="female"),
                RB.build_demographic("Age > 65", term="age", details="> 65"),
                RB.build_condition("hypertension"),
            ]
        )
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert "p.gender" in sql, f"gender predicate missing; sql=\n{sql}"
        assert "p.birth_date" in sql, f"age predicate missing; sql=\n{sql}"
        assert "condition_simple" in sql, f"diagnosis predicate missing; sql=\n{sql}"
        assert "female" in params.values(), f"gender param not bound; params={params}"

    def test_single_demographic_age_only_produces_age_predicate(self, gen):
        """Single-demographic regression sanity. No gender; just age + diagnosis."""
        reqs = RB.build_requirements(
            inclusion=[
                RB.build_demographic("Age > 50", term="age", details="> 50"),
                RB.build_condition("diabetes"),
            ]
        )
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert "p.birth_date" in sql, f"age predicate missing; sql=\n{sql}"
        assert "condition_simple" in sql, f"diagnosis predicate missing; sql=\n{sql}"
        assert "p.gender" not in sql, f"unexpected gender predicate; sql=\n{sql}"

    def test_age_range_combined_with_gender_emits_all_three_predicates(self, gen):
        """The full failure pattern from Phase 2 stress test: gender + age-range +
        diagnosis. Pre-fix, only gender + diagnosis reached the WHERE clause
        because the age-range parse failed silently.
        """
        reqs = RB.build_requirements(
            inclusion=[
                RB.build_demographic("Female", term="gender", details="female"),
                RB.build_demographic("Age 40-65", term="age", details="between 40 and 65"),
                RB.build_condition("diabetes"),
            ]
        )
        sql, params = gen.generate_phenotype_sql(reqs, count_only=True)
        assert "p.gender" in sql, f"gender predicate missing; sql=\n{sql}"
        assert "BETWEEN" in sql, f"age range predicate missing; sql=\n{sql}"
        assert "condition_simple" in sql, f"diagnosis predicate missing; sql=\n{sql}"


class TestIssue51ParseAgeDetailsUnit:
    """Unit coverage on _parse_age_details directly. Pins the return-shape
    contract: (op, value) for comparisons, ('BETWEEN', (lo, hi)) for ranges,
    (None, None) for unparseable input.
    """

    @pytest.mark.parametrize(
        "details,expected",
        [
            ("between 18 and 65", ("BETWEEN", (18, 65))),
            ("between 5 and 12", ("BETWEEN", (5, 12))),
            ("between 40 and 65", ("BETWEEN", (40, 65))),
            ("between 20 and 29 (in their 20s)", ("BETWEEN", (20, 29))),
            # comparison ops still work (no regression)
            ("> 18", (">", 18)),
            ("greater than 18", (">", 18)),
            ("over 65", (">", 65)),
            ("< 18", ("<", 18)),
            ("under 18", ("<", 18)),
            ("less than 65", ("<", 65)),
        ],
    )
    def test_parse_age_details_returns_expected_shape(self, details, expected):
        assert SQLGenerator._parse_age_details(details) == expected

    @pytest.mark.parametrize(
        "details",
        [
            "",
            "elderly",  # no op + no number
            "ancient",  # no op + no number
        ],
    )
    def test_parse_age_details_returns_none_for_unparseable(self, details):
        assert SQLGenerator._parse_age_details(details) == (None, None)


@pytest.mark.requires_api_key
class TestIssue51LLMPromptDiagnostic:
    """Diagnostic verification that the LLM prompt produces the expected
    concept shape at time of writing. May flake on model behavior shifts;
    failures here should be investigated for prompt-output drift before
    treated as code regressions.

    Gated by @pytest.mark.requires_api_key (project convention). CI excludes
    these via `-m 'not requires_api_key'`; run locally with API key in .env.
    """

    @pytest.fixture
    def agent(self):
        from app.agents.requirements_agent import RequirementsAgent

        return RequirementsAgent()

    @pytest.mark.asyncio
    async def test_llm_emits_separate_concepts_for_male_diabetic_age_input(self, agent):
        """The canonical #51 input: verify the LLM emits 3 separate concepts
        (gender, age, diabetes) per its prompt instructions, not a compound
        term that would trip _build_demographic_clause's age-first dispatch.
        """
        structured = await agent._criteria_to_structured(
            ["male diabetic patients above the age of 18"]
        )
        assert len(structured) == 1
        concepts = structured[0]["concepts"]
        types = {c["type"] for c in concepts}
        terms = {c.get("term", "").lower() for c in concepts}

        # gender + age must be separate demographic concepts
        gender_concepts = [
            c
            for c in concepts
            if c["type"] == "demographic" and "gender" in c.get("term", "").lower()
        ]
        age_concepts = [
            c for c in concepts if c["type"] == "demographic" and "age" in c.get("term", "").lower()
        ]
        condition_concepts = [c for c in concepts if c["type"] == "condition"]

        assert gender_concepts, f"LLM did not emit a gender concept; got: {concepts}"
        assert age_concepts, f"LLM did not emit an age concept; got: {concepts}"
        assert condition_concepts, f"LLM did not emit a condition concept; got: {concepts}"

    @pytest.mark.asyncio
    async def test_llm_emits_between_range_for_age_range_input(self, agent):
        """Verify the LLM emits "between X and Y" details format for age-range
        phrasings — this is the exact failure shape Phase 2 stress test
        surfaced, and the contract `_parse_age_details` now relies on.
        """
        structured = await agent._criteria_to_structured(
            ["male patients aged 40 to 65 with hypertension"]
        )
        concepts = structured[0]["concepts"]
        age_concepts = [
            c for c in concepts if c["type"] == "demographic" and "age" in c.get("term", "").lower()
        ]
        assert age_concepts, f"LLM did not emit an age concept; got: {concepts}"
        details = age_concepts[0].get("details", "").lower()
        assert (
            "between" in details and "40" in details and "65" in details
        ), f"LLM did not emit 'between X and Y' format; got: {details!r}"
