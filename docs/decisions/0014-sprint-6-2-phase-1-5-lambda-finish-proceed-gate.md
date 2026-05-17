---
sprint: 6.2
date: 2026-05-09
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 6.2 Phase 1.5 — PROCEED to Phase 2 (gate cleared at 7/7, anchors all PASS)

The pre-committed pivot rule from the lambda-finish design doc said: **"≥6/7 PASS, ALL 3 anchors PASS → PROCEED to Phase 2; <6/7 OR any anchor FAIL → pivot to Pathling-only Approach B (3 weeks)."** Issue #14 milestone applies the rule against the harness output after issues #10-#13 + #16.

**Gate result, 2026-05-09:** **PROCEED.** Every criterion exceeds threshold:

| Criterion | Required | Actual | Verified by |
|---|---|---|---|
| View-level PASS rate | ≥6/7 | **7/7** | harness 48/48 |
| Anchor PASS (mandatory) | 3/3 | **3/3** | sample_values for patient_simple, patient_demographics, condition_simple |
| Bug 9 production callsite verified | yes | 7/7 | mvr_get_schema test parametrized over all view defs |
| UNIQUE INDEX for CONCURRENTLY refresh | per MV | 7/7 | test_unique_index_on_id |

**The Q1 refinement was load-bearing.** The original pivot rule would have fired during issue #11 implementation when uncataloged Bugs 10/11/12 surfaced (and again in #12 when Bugs 13/14/15 surfaced). The Q1 refinement (cataloged-bug fixes are Phase 1.2 scope, NOT pivot triggers) let the work proceed: each newly-discovered bug got added to the design doc bugs table and fixed in scope. **Catalog grew from planned 9 to actual 15 bugs** — every one mechanical or scoped-structural, none "transpiler can't do FHIRPath feature X." Pre-committing the refinement before implementation prevented mid-sprint pressure from forcing a Pathling rewrite that wasn't actually warranted.

**No Pathling fallback evaluation needed.** The pre-committed 5/7 PASS scenario (which would have triggered Pathling-fallback for stragglers) never materialized — every view def transpiled with the custom transpiler after bug fixes.

**Notable narrative side-effects:**
- The `/qa` mutation testing pattern (Mutation 1 for Bug 1, Mutation 2 for Bug 9) proved the harness's PASS/FAIL signal was sensitive enough BEFORE any bug fix was attempted. When the actual fixes shipped in #10 and #13, both flipped exactly as the mutations predicted — zero surprises.
- The harness caught its own author's bugs DURING TDD: cycle 2 of issue #9 (information_schema vs pg_attribute), cycle 6 of issue #12 (Bug 13 v1 over-aggressive scalar-leaf detection that regressed patient_demographics). Both fixed before any production code trusted false signals.
- The grilling pattern compounded: each `/tdd` cycle exposed at least one uncataloged bug that planning didn't predict. Issues #11, #12, #16 each grew their scope by 1-3 bugs as new manifestations surfaced. Per-issue scope expansion is recorded in commit messages so future-me can trace why each cluster shipped together.

**Phase 2 unblocked.** Phase 1.6 (issue #15 — switch streamlit demo to MV path) now safe to execute. Phase 2.0 (poll-based speed layer + on-demand refresh endpoint) and Phase 2.1 (HybridRunner merge + dedup) follow per design doc.
