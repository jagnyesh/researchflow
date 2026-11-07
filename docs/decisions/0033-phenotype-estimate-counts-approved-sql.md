---
sprint: null
date: 2026-11-04
status: accepted
supersedes: []
superseded_by: null
related: [0027-sprint-6-5-differential-freshness-routing.md, 0029-api-error-path-phi-safe-500s.md]
---

# The phenotype estimate counts the approved SQL (#206)

**Amends** ADR 0027 for its only production `FORMAL_DRAFT` caller. ADR 0027 is left unedited, following the append-only convention.

**Problem.** `phenotype_agent` estimated the cohort with a second implementation of the criteria. It ran `HybridRunner` over `patient_simple` in `FORMAL_DRAFT` mode, speed-merged, then filtered rows in Python. That path dropped the concept shapes the requirements agent actually emits:
- `term: "gender"` produced no search parameter.
- `term: "age"` with `"> 65"` fell through `_filter_by_age`'s "return everyone" branch.
- The condition matched more broadly than the SQL does.

For REQ-20261030-B2B6AD86 (female, over 65, diabetes mellitus), the estimate shown to the G2 reviewer was **156**. The phenotype SQL being approved returns **13**.

**Decision (owner, 2026-11-04).** The estimate is `COUNT(DISTINCT patient_id)` over the phenotype SQL and its bound parameters, the same SQL the G2 reviewer approves and the extraction runs. It reads the batch tables.
- This gives one cohort definition. The estimate can't disagree with the approved SQL, and an unrecognized criterion can't silently widen the cohort.
- The HybridRunner path, the Python filters and the uncalled `InMemoryRunner` methods are deleted.

**Consequences.**
- The estimate no longer speed-merges patients who arrived since the last batch refresh. `FORMAL_DRAFT` therefore has no production caller, as `FORMAL_EXTRACTION` already didn't. The mode stays implemented and unit-tested in `HybridRunner`.
- `phenotype_agent` no longer writes `hybrid_runner_metrics` rows. The `caller='phenotype_agent'` wiring test in `test_hybrid_runner_freshness.py` is removed.
- A failed estimate still raises `CohortEstimateUnavailable` (#245) and never becomes a number.
- Tests: `tests/test_cohort_estimate_from_sql.py`, live and read-only. With #206's concept shapes, the estimate equals the phenotype SQL's count: 13, where it was 156 before.
