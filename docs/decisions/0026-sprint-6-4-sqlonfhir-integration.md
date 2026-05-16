---
sprint: 6.4
date: 2026-05-15
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 6.4 — sqlonfhir integration: dispatch-on-runner_hint + 3 zero-row MVs ported + post-write health check

Sprint 6.3's verdict (revised same-day to GO sqlonfhir) committed the project to swapping the FHIRPath engine for 3 view-defs the custom transpiler couldn't deliver (observation_labs + condition_diagnoses both had non-trivial `where(...)` filters; procedure_history needed `forEachOrNull` outer-join semantics). Sprint 6.4 ships that swap with the smallest possible blast radius: per-view-def opt-in via a `runner_hint` field, two backend methods on `ViewMaterializer`, and the existing custom path unchanged for the 4 MVs it already serves correctly.

### Five coupled decisions (locked into issue #40 pre-implementation grilling)

**(1) Dispatch granularity — per-view-def `runner_hint`, NOT per-resource-type or per-environment env var.** Per-view-def lets the 3 sqlonfhir-target view-defs each declare their backend choice in their own JSON file (`"runner_hint": "sqlonfhir"`). The 4 working custom-path MVs (patient_simple, patient_demographics, condition_simple, medication_requests) declare nothing and default to custom. Per-resource-type ("all Conditions go through sqlonfhir") was rejected — condition_simple works correctly via custom today and forcing it into the new backend would expand blast radius without payoff. Env var ("USE_SQLONFHIR=true") was rejected — it's the same trap as Sprint 6.1 Phase 2.2's no-AUDIT_ENABLED rule: a flag that lets the wrong path stay live indefinitely. Per-view-def opt-in makes the routing decision read directly from the view-def the dispatcher is processing.

**(2) Storage shape asymmetry accepted — custom path writes `CREATE MATERIALIZED VIEW`, sqlonfhir path writes `CREATE TABLE + TRUNCATE + INSERT`.** The custom backend produces a SQL string that Postgres can materialize; the sqlonfhir backend produces rows in memory (via `sqlonfhir.evaluate()`). Two storage shapes for the same logical surface (`sqlonfhir.<view_name>`). Trade accepted: type-aware DROP via `pg_class.relkind` lookup (returns bytes `b"r"` for table vs `b"m"` for materialized view — asyncpg-specific gotcha worth documenting), and CONCURRENTLY refresh is no longer available for sqlonfhir-path MVs. Pre-aligning the storage shape (e.g., writing the sqlonfhir output back through `CREATE MATERIALIZED VIEW AS SELECT ... FROM jsonb_to_recordset(...)`) was considered and rejected — it adds ~50 lines of JSON-to-Postgres marshaling for negligible operational benefit (the batch refresh path doesn't run concurrently with reads anyway; the existing `materialize_views.py` is invoked manually or nightly).

**(3) Health-check detection mechanism — same-run oracle, 5% per-run threshold, N=3 consecutive-warn alarm filter, JSONL output.** Same-run oracle (query HAPI count and MV row count at the same materialization moment) is data-drift-immune: the oracle moves with the data, so a delta between MV and oracle is a code regression, not a fixture drift. 5% per-run threshold is the slack against transient HAPI consistency hiccups. N=3 consecutive-warn alarm filters single-run noise — one warn doesn't fire the alarm; three in a row does. JSONL output keeps the log machine-parseable and append-only; the dashboard reads the tail. Residual risk: if the bug introduces a CONSISTENT 5%+ delta across runs, the alarm only fires after 3 batch refreshes — accepted because the alternative (alarm on first warn) is noisier in practice.

**(4) Health-check scope — sqlonfhir MVs only this sprint; custom-path MV oracles deferred.** The 3 sqlonfhir-target MVs have explicit oracle queries in `tests/fixtures/mv_row_count_oracles.sql` (with documented WHERE-clause replication + data observations). The 4 custom-path MVs do NOT have oracle queries this sprint — adding them would be marginal: cycle 7's regression test already verifies the row count anchors against raw resource counts (no WHERE clauses on any of the 4), and the transpiler harness (Sprint 6.2 Phase 1.1, 48/48 tests) is the existing regression net. Filed as Sprint 6.6 candidate to add oracles for the custom-path MVs if a future bug surfaces that the transpiler harness misses.

**(5) Test surface — wire-level integration for both backends; the unit-only level cannot catch the routing bug.** Each backend gets one end-to-end integration test parametrized over its set of MVs: `test_sqlonfhir_integration.py` covers the 3 sqlonfhir-path MVs; `test_custom_path_regression.py` covers the 4 custom-path MVs. Both gated by `@pytest.mark.requires_hapi` so the suite runs cleanly offline. Dispatch unit tests (`test_backend_dispatcher.py`) cover the routing primitive in isolation. Same structural lesson as Sprint 8.2 PR #45: when the system under test depends on third-party library shape (here: sqlonfhir's evaluate() output, asyncpg's pg_class return type), assert at the wire, not the wrapper.

### Empirical outcome (2026-05-15)

All 6 pre-committed gates GREEN. Full HAPI-gated suite: **35/35 PASS in ~88s**.

| Gate | Target | Measured | Status |
|---|---|---|:---:|
| #1 row count ≤1% of oracle, sqlonfhir MVs | 3/3 within tolerance | 3/3 exact match (0.00% delta) | ✓ |
| #2 4 custom-path MVs unchanged | 4/4 within 1% | 4/4 exact match | ✓ |
| #3 observation_labs materialize ≤60s | ≤60.0s | 53.7s (6s headroom) | ✓ |
| #4 audit middleware unchanged | no audit-touching code | no audit-touching code | ✓ |
| #5 dispatch unit test exists | yes | 4 unit tests in test_backend_dispatcher.py | ✓ |
| #6 sqlonfhir equivalence (Sprint 6.3) | 3/3 match HAPI oracle | 3/3 + same-run health check ongoing | ✓ |

Three sqlonfhir MVs land at expected counts:
- `condition_diagnoses`: 14,832 rows (matches HAPI oracle exactly)
- `observation_labs`: 157,689 rows (matches HAPI oracle exactly)
- `procedure_history`: 66,448 rows (matches HAPI oracle exactly)

### What this sprint NOTABLY did NOT do

- **Did not flip any agents through HybridRunner.** Sprint 6.2 architectural gap (production agents bypass the Runner stack) is unchanged. Sprint 6.5 candidate.
- **Did not change the API surface to materialized_views router.** Sprint 6.1 Phase 2.5 admin-gating and view_name allowlist remain in place; no new endpoints; no migration of existing endpoints.
- **Did not migrate condition_simple from custom to sqlonfhir.** It works correctly via custom; per D1, opt-in is per-view-def. If a future ingestion adds resources where condition_simple's transpiled SQL produces wrong rows, that's the migration trigger; not now.
- **Did not retire the custom-FHIRPath transpiler.** It serves 4 MVs correctly and the Sprint 6.2 Phase 1.1 transpiler harness (48/48 tests) is the regression net for ALL of them. Sprint 6.4 narrows the transpiler's scope, doesn't remove it.

### Eight-cycle structure (vertical-slice /tdd, one RED→GREEN per cycle)

The sprint shipped across 8 commits on `feature/sprint-6-4-sqlonfhir-integration`:

| Cycle | Tracer bullet | Commit |
|---|---|---|
| 1 | Backend dispatch primitive + 4 unit tests | `7e1afaa` |
| 2 | ViewMaterializer dispatch integration | `0a63f1e` |
| 3 | sqlonfhir end-to-end for condition_diagnoses | `b4d7d76` |
| 4 | observation_labs + procedure_history via sqlonfhir | `d5d2e82` |
| 5 | post-write MV health check + jsonl logging | `9eed8e2` |
| 6 | admin-dashboard MV health surface | `401e8c0` |
| 7 | custom-path MV regression check | `60abeff` |
| 8 | sprint close docs (this commit) | tba |

Each cycle added ≤1 new module + its tests, kept the full suite GREEN, and was self-demoable. Cycle 4's sub-decision (architectural asymmetry around CREATE TABLE vs MATERIALIZED VIEW) was the only one that required mid-sprint design adjustment — captured in cycle 4's commit message and decision (2) above.

### Discipline notes — what made this sprint work

**(a) Locked pre-commits into issue #40 body before code work.** The Sprint 6.3 verdict-revision precedent established that pre-commits defend against bias, not information. Sprint 6.4's grilling produced 6 numeric gates that became the test-suite's structure (each gate = an assertion in a specific test file). Cycle 7 in particular existed only because gate #2 demanded explicit verification — without the pre-commit, the temptation would have been "the existing transpiler harness covers it." Empirically it does, but the new test catches a regression class (mis-dispatching to sqlonfhir for a custom-path view-def) that the harness can't.

**(b) Sub-decision surfaced mid-sprint, captured in commit message + ADR.** Before cycle 3, the implementing agent surfaced "the sqlonfhir backend produces rows, not SQL — we can't write through CREATE MATERIALIZED VIEW." User chose B (embrace the asymmetry) over A (marshal rows back through a SELECT-from-VALUES MV) with explicit rationale documented in cycle 3's commit. Decision (2) above is the formal capture. Sub-decisions caught at implementation time, not at design time, are the cheapest cost-of-change.

**(c) Cycle 4 surfaced an asyncpg-specific gotcha.** `pg_class.relkind` returns `bytes` (b"r"/b"m") under asyncpg, not `str`. The DROP-by-type dispatcher silently failed until the bytes comparison was added. Lesson: typed comparisons at trust-boundary reads (DB return values are a trust boundary, same as third-party library outputs). Sprint 8.2's structural lesson generalizes: assert against the wire shape, not the wrapper shape.

**(d) Lean-ctx tools used through the sprint after the user called out the prior session's drift.** ctx_read, ctx_search, ctx_edit, ctx_shell replaced native Read/Bash/Edit where applicable. Cycle 4 onward. The token-efficiency win was material on a sprint that touched 8 commits across the lifetime of the work.

### Sprint 6.4 closes

Issues closed by this sprint's merge:
- `#40` Sprint 6.4 — sqlonfhir integration + dispatch plumbing + port 3 zero-row MVs
- `#41` procedure_history view-def `forEachOrNull` fix (landed with Sprint 6.3 spike PR; verified in cycle 4)

Filed by this sprint:
- **Sprint 6.6 candidate** — custom-path MV health-check oracles. The 4 custom-path MVs currently rely on the transpiler harness for regression coverage; adding explicit oracles (raw resource count anchors per cycle 7's pattern, plus any WHERE-clause replication if a custom view-def later gains a WHERE) would unify the health-check surface for all 7 MVs. File when transpiler harness misses a regression OR when a custom view-def gains a non-trivial WHERE clause.

### Sprint 7.2 unblocked

Per the Sprint 7.2 ADR's sequencing rationale ("Sprint 6.4 closes → Sprint 7.2 starts → Sprint 6.5 starts"), the A2A FSM to LangGraph migration close-out is now the next-up sprint. Sprint 6.5 (agents through HybridRunner) waits behind 7.2 to avoid forcing the wiring change in both orchestrations.
