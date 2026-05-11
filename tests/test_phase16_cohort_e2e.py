"""Phase 1.6 E2E test (issue #15) — cohort query via HybridRunner→MV path.

Verifies the production query path that the harness underwrites:
- Streamlit research_notebook → FeasibilityService.execute_feasibility_check
- → JoinQueryBuilder builds SQL JOIN against sqlonfhir.patient_demographics
   + sqlonfhir.condition_simple
- → execute against hapi-postgres directly

Issue #9's harness verifies the materialized views are CORRECT (per-row,
per-column). This test verifies the production CONSUMPTION path actually
hits those views and meets Phase 1.6's latency criterion.

Cohort sizes are tied to the 5-patient hand-curated fixture in
tests/fixtures/hapi_seed/bundle.json (replaced the Synthea-based dump on
2026-05-11 per /plan-eng-review). The JoinQueryBuilder OR-matches across
icd10_code + code_text (3-column fallback from CONTEXT.md), so:

- Female + diabetes (E1%): cohort=1 (just fixture-patient-d). Patient B is
  female with hypertension SNOMED-only — code_text="Essential hypertension
  (disorder)" doesn't match '%diabetes%' so she's excluded.
- Male + hypertension (I10%): cohort=2 (fixture-patient-a via icd10_code
  I10; fixture-patient-e via code_text ILIKE '%hypertens%'). Patient E
  has SNOMED-only coding so the I10% column-match fails, but the OR-fallback
  on code_text catches "Essential hypertension (disorder)". Patient C is
  male with diabetes only — excluded.

The icd10_code NULL path (Bugs #4/5/6 coverage for filter-no-match) stays
exercised by patients B/E whose icd10_* columns are NULL in condition_simple.
"""

import time

import pytest

pytestmark = pytest.mark.requires_services

from app.services.feasibility_service import FeasibilityService

# The canonical "female patients with diabetes" query intent that streamlit
# research_notebook produces. Mirrors what QueryInterpreter generates for
# this natural-language query.
CANONICAL_QUERY_INTENT = {
    "view_definitions": ["patient_demographics", "condition_simple"],
    "search_params": {"gender": "female"},
    "post_filters": [
        {
            "field": "icd10_code",
            "value": "E1%",
            "condition_name": "Diabetes mellitus (all types)",
            "use_like": True,
        }
    ],
    "data_elements": [],
    "aggregation_type": "count",
}


@pytest.mark.asyncio
async def test_canonical_query_hits_mv_path(materialized_views):
    """Cohort query hits sqlonfhir.* via SQL JOIN, not InMemoryRunner.

    Most important Phase 1.6 assertion: the SQL actually contains references
    to the sqlonfhir schema. If FeasibilityService had silently fallen back
    to InMemoryRunner (REST-to-HAPI), the SQL field would be empty or refer
    to HAPI internal tables, not materialized views.
    """
    fs = FeasibilityService()
    result = await fs.execute_feasibility_check(CANONICAL_QUERY_INTENT)

    sql = result.get("generated_sql", "")
    assert (
        "sqlonfhir.patient_demographics" in sql
    ), f"Expected SQL to reference sqlonfhir.patient_demographics MV path; got:\n{sql}"
    assert (
        "sqlonfhir.condition_simple" in sql
    ), f"Expected SQL to reference sqlonfhir.condition_simple MV path; got:\n{sql}"


@pytest.mark.asyncio
async def test_canonical_query_returns_nonempty_cohort(materialized_views):
    """The MV-based JOIN returns a real cohort (proves the views have data).

    Asserts cohort is exactly 1 against the 5-patient fixture: only
    fixture-patient-d is female AND has a Condition with ICD-10 E11.9.
    fixture-patient-c is male (filtered out by gender) and patient B has
    hypertension as SNOMED-only (no ICD-10, so the E1% LIKE filter
    yields NULL).
    """
    fs = FeasibilityService()
    result = await fs.execute_feasibility_check(CANONICAL_QUERY_INTENT)

    cohort = result.get("estimated_cohort", 0)
    assert cohort == 1, (
        f"Expected cohort=1 (just fixture-patient-d) for the 5-patient fixture; "
        f"got {cohort}. 0 = filter regressed or fixture-d's icd10_code is missing; "
        f">1 = unintended cross-gender match."
    )


@pytest.mark.asyncio
async def test_canonical_query_meets_latency_target(materialized_views):
    """Phase 1.6 acceptance: <100ms via MV path (was 549ms via InMemoryRunner).

    Measures 3 warm runs, asserts the 3rd-run latency is under 100ms. First
    run can include lazy DB pool warmup; we care about the steady-state
    latency a researcher would actually experience.
    """
    fs = FeasibilityService()

    # Warmup
    await fs.execute_feasibility_check(CANONICAL_QUERY_INTENT)
    await fs.execute_feasibility_check(CANONICAL_QUERY_INTENT)

    # Measured run
    t0 = time.perf_counter()
    await fs.execute_feasibility_check(CANONICAL_QUERY_INTENT)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 100.0, (
        f"Expected MV-path query under 100ms; got {elapsed_ms:.1f}ms. "
        f"InMemoryRunner baseline was 549ms (43x slower); this should be ~10ms via MV."
    )


# Regression case from issue #15 acceptance criteria: a different canonical
# query must also hit the MV path with reasonable cohort + latency. Catches
# the failure mode where "diabetes" works but other phenotypes silently fall
# back or zero-cohort. Issue body literal "Male patients 65+" reframed: the
# JoinQueryBuilder's post_filters target the condition_simple table, not
# patient-level columns like birth_date. A patient-level age filter would
# be a separate JoinQueryBuilder feature; for the regression intent we
# substitute a different gender+condition pair, which exercises the same
# code path with different inputs and catches gender-specific or
# condition-specific regressions.
MALE_HYPERTENSION_QUERY_INTENT = {
    "view_definitions": ["patient_demographics", "condition_simple"],
    "search_params": {"gender": "male"},
    "post_filters": [
        {
            "field": "icd10_code",
            "value": "I10%",
            "condition_name": "Essential hypertension",
            "use_like": True,
        }
    ],
    "data_elements": [],
    "aggregation_type": "count",
}


@pytest.mark.asyncio
async def test_male_hypertension_regression_hits_mv_path(materialized_views):
    """Regression for issue #15: a different gender+condition pair must
    also use the MV path. Without this, a fix that works for "female +
    diabetes" but silently breaks for any other combination would slip
    through.
    """
    fs = FeasibilityService()
    result = await fs.execute_feasibility_check(MALE_HYPERTENSION_QUERY_INTENT)

    sql = result.get("generated_sql", "")
    assert (
        "sqlonfhir.patient_demographics" in sql
    ), f"Male+hypertension query must hit MV path, not InMemoryRunner; got SQL:\n{sql}"
    assert (
        "sqlonfhir.condition_simple" in sql
    ), f"Male+hypertension query must JOIN condition_simple MV; got SQL:\n{sql}"

    cohort = result.get("estimated_cohort", 0)
    assert cohort == 2, (
        f"Expected cohort=2 (fixture-patient-a + fixture-patient-e) for the 5-patient fixture; "
        f"got {cohort}. The JoinQueryBuilder ORs icd10_code LIKE 'I10%' with code_text ILIKE '%hypertens%', "
        f"so patient A matches via ICD-10 and patient E matches via code_text. "
        f"<2 = OR-fallback regressed; >2 = unintended cross-gender or diabetes match."
    )


@pytest.mark.skip(
    reason=(
        "Architectural gap: streamlit research_notebook calls FeasibilityService "
        "directly (not via HTTP/API), so the audit middleware never fires for "
        "cohort queries. Issue #15's audit-log acceptance criterion would require "
        "either (a) an audit-record write inside FeasibilityService.execute_"
        "feasibility_check, or (b) a /feasibility HTTP endpoint that the UI calls. "
        "Tracking as a follow-up issue rather than blocking the rest of #15."
    )
)
@pytest.mark.asyncio
async def test_cohort_query_writes_analyticsview_audit_record(materialized_views):
    """Acceptance criterion #5 from issue #15 — currently architecturally unmet."""
    pass
