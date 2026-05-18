# ResearchFlow — Current State

**Sprint:** 6.5b next (#71) — extraction_agent + feasibility_service multi-view JOIN wiring through HybridRunner. Deferred from Sprint 6.5 Phase 2B-2 audit (all 4 extraction sql_adapter sites are multi-view JOIN / IN-list shapes that don't fit HybridRunner's single-view-def API; needs API extension first).
**Branch:** main is fresh after Sprint 6.5 merge; feature branch TBD when Sprint 6.5b starts.
**Recently shipped:** Sprint 6.5 SHIPPED 2026-05-17 as squash PR #78 (`d457fe8`) — `HybridRunner` now has its first production caller (`phenotype_agent`) with three-mode `FreshnessAnnotation` routing (EXPLORATORY / FORMAL_DRAFT / FORMAL_EXTRACTION). 8/8 gate assertions GREEN; ADR 0027. Sprint 7.2 SHIPPED 2026-05-17 (23 commits) — A2A FSM retired, LangGraph is the only orchestrator. Sprint 6.4 SHIPPED 2026-05-15 as `b64d0d8` (sqlonfhir integration). Sprint 8 series CLOSED 2026-05-14. Sprint 6.1/6.2 SHIPPED 2026-05-08.
**Overall progress:** Sprint 6.5 SHIPPED 2026-05-17, Sprint 7.2 SHIPPED 2026-05-17, Sprint 6.4 SHIPPED 2026-05-15, Sprint 8 series closed 2026-05-14, Sprint 6.1/6.2 SHIPPED 2026-05-08. **~20/22 sprints shipped.** A2A FSM permanently retired; HybridRunner has its first production caller.
**Last updated:** 2026-05-17

## Sprint 6.5 SHIPPED (2026-05-17 as `d457fe8`) — Lambda differential freshness routing

19 commits, ~2,400 net insertions, squash PR #78. The documented-but-uncalled `HybridRunner` serving layer now has its first production caller: `phenotype_agent` routes through `HybridRunner.execute(..., mode=FreshnessAnnotation.FORMAL_DRAFT, caller="phenotype_agent")` at both cohort-estimation + condition-filter callsites. Three-mode freshness routing landed end-to-end. See [`docs/decisions/0027-sprint-6-5-differential-freshness-routing.md`](docs/decisions/0027-sprint-6-5-differential-freshness-routing.md) for the per-phase commit ledger + 5 coupled grilling decisions.

### Phase ledger

| Phase | Outcome |
|---|---|
| 1 (#68 writer + metadata) | `f3f21d7` — `scripts/drive_fhir_traffic.py` synthetic FHIR writer with `--cohort` presets (t2dm, hypertension) + `sqlonfhir.mv_refresh_metadata` table for `batch_anchor_ts` citation anchors; `materialize_views.py` records refresh completions across all 3 paths |
| 2A (#69 HybridRunner core, 8 /tdd cycles) | `7424621` → `f4f4416` — `FreshnessAnnotation` enum + three-mode routing in `HybridRunner.execute()` + `HybridRunnerMetric` single-source-of-truth dataclass + Postgres `hybrid_runner_metrics` writes + `suppress_metrics=True` escape + LangSmith `RunTree.add_metadata` mirroring + `get_batch_anchor_ts_for_views` multi-view MAX |
| 2B-1 (#70 phenotype wiring) | `f71ac4e` — `phenotype_agent.use_view_definitions = True` (toggle flipped post-pre-flight; Sprint 6.2-era "broken" comment was stale per Path-0 diagnostic); HybridRunner instantiated with Redis + caching; both call sites pass `mode=FORMAL_DRAFT, caller="phenotype_agent"` |
| 2B-2 (#70 extraction audit) | `7f87662` — empirical audit found all 4 extraction sql_adapter sites are multi-view JOIN or raw-table-ref IN-list shapes that don't fit HybridRunner's single-view-def API; deferred to #71 (Sprint 6.5b candidate) |
| 2B-3 (#70 phenotype integration test) | `4140a34` — focused agent-boundary test (pivoted from path-i after /diagnose found `test_nlp_to_sql_workflow` is LLM-judgment-flaky for whole file; filed #75) |
| 4 (#72 gate) | `dbb016c` — `scripts/sprint_6_5_gate.py` 7-step gate fires 8/8 assertions GREEN against synthetic t2dm cohort writes; JSONL evidence at `logs/sprint_6_5_gate.jsonl` |
| Close + production-walkthrough fixes | `49643c6` (ADR 0027 + CONTEXT.md + INDEX.md), `d1c8a04` (admin dashboard Sprint 7.2 migration gap — `LangGraphRequestFacade.agents = {}` empty; refactored panel to query distinct `agent_executions.agent_id`), `2d0b472` (extraction silent-failure honesty patch surfacing `extraction_warnings` in delivery README), plus 2 CI fixes (`f1e548a` F821 forward-ref import, `3cb1537` CodeQL FP on synthetic Patient IDs) |

### Gate evidence (Phase 4 empirical run 2026-05-17)

| Assertion | Result |
|---|---|
| `redis_speed_layer_seeded` | 5 t2dm patient keys present ✅ |
| `exploratory_row_count` | 47 (N+5=42+5) — speed-merged ✅ |
| `formal_draft_row_count` | 47 (N+5) — speed-merged ✅ |
| `formal_draft_freshness` | 1s (< 90s bound) ✅ |
| `formal_extraction_count` | 42 (N, batch-only — speed layer NOT merged) ✅ |
| `formal_extraction_anchor` | exact match w/ `mv_refresh_metadata.MAX(refreshed_at)` ✅ |
| `langsmith_cross_correlation` | RunTree metadata mirrors Postgres `hybrid_runner_metrics` exactly ✅ |
| **Blockers** | **0** ✅ |

### Issues filed during sprint (non-blocking)

- **[#71](https://github.com/jagnyesh/researchflow/issues/71)** — Sprint 6.5b candidate: extraction_agent + feasibility_service multi-view JOIN wiring (HybridRunner API extension needed first).
- **[#74](https://github.com/jagnyesh/researchflow/issues/74)** — `test_phase20a_speed_layer` flake on soft-deleted Patients (test bug, not production).
- **[#75](https://github.com/jagnyesh/researchflow/issues/75)** — `test_nlp_to_sql_workflow` LLM-judgment-flaky for whole file.
- **[#76](https://github.com/jagnyesh/researchflow/issues/76)** — Exploratory portal age-filter analysis (manual REQ-20260517-A097C5F6 walkthrough).

### Next per BACKLOG

- **Sprint 6.5b** ([#71](https://github.com/jagnyesh/researchflow/issues/71)) — extraction_agent + feasibility_service multi-view JOIN wiring through HybridRunner.
- **Sprint 6.6 candidate** — custom-path MV health-check oracles (filed by Sprint 6.4).
- **Sprint 8.5/8.6 candidates** — sparse-traffic median + exploratory portal caching.

---

## Sprint 7.2 SHIPPED (2026-05-17) — A2A FSM retired

23 commits across one session. The 1,324 LOC A2A FSM under `app/orchestrator/` is permanently gone. LangGraph is the only orchestrator. See [`docs/decisions/0024-sprint-7-2-a2a-fsm-closeout.md`](docs/decisions/0024-sprint-7-2-a2a-fsm-closeout.md) for the full close ADR with per-phase commit ledger + meta-pattern lessons.

| Phase | Outcome |
|---|---|
| 0 — WorkflowState promotion | `100ef8c` — schema enum moved to `app/database/workflow_states.py`; 8 importers re-routed |
| 1 — Parity verification | `697bcf9` close addendum — 8 /tdd cycles, 22 unit tests, harness produced `logs/sprint_7_2_parity.jsonl` evidence artifact; Path-0 diagnostic re-framed the literal "FAILED gate" verdict as 3 pre-existing observations (Findings 1+2+3, none Sprint-7.2-introduced) |
| 2 — Template default flip | `e14908b` — `USE_LANGGRAPH_WORKFLOW=true` in `config/.env.example` |
| 3 — Migrate/retire 7 scripts | `c845d75` — 3 migrated, 4 deleted (`route_task` was a no-op in LG); + new `docs/operations/stuck-request-recovery.md` runbook |
| 4+5 — Delete A2A + simplify dispatchers | `2b7d72d` — **-2,386 LOC** (1,324 A2A FSM + orphan dev scripts; production dispatchers in `researcher_portal.py` + `admin_dashboard.py` + `app/main.py` + `app/api/approvals.py` + `app/services/approval_service.py` all migrated to `LangGraphRequestFacade`) |
| 6 (partial — D-hybrid) | `3950eed` — `test_nlp_to_sql_workflow.py` ported (3 tests, schema-drift bug fixed); 2 files deferred to Sprint 7.3 candidate ([#65](https://github.com/jagnyesh/researchflow/issues/65)) |
| 7 — Close ADR + this doc update | (this commit) |

**Net codebase change:** ~-3,200 LOC across the sprint. The project shrunk meaningfully while gaining the parity verification harness as the evidence artifact for the deletion.

### Issues filed by Sprint 7.2 (not blockers; documented separately)

- **[#63](https://github.com/jagnyesh/researchflow/issues/63)** — `state_history` persistence gap (medium, both orchestrators pre-existing). Workflow transitions update in-memory state but never `UPDATE research_requests.state_history`.
- **[#64](https://github.com/jagnyesh/researchflow/issues/64)** — PHI access audit not firing for agent-driven workflows (HIGH, compliance, pre-existing since Sprint 6.1). The audit middleware fires for HTTP routes only; the production data path bypasses FastAPI.
- **[#65](https://github.com/jagnyesh/researchflow/issues/65)** — Sprint 7.3 candidate: port the 2 remaining A2A behavioral test files (`test_agent_handoffs.py`, `test_admin_dashboard_updates.py`) to LangGraph. ~14-20 hours per inspection-time triage.

### Next per BACKLOG

- **Sprint 6.5** — wire agents through `HybridRunner` for online reads. Sprint 7.2 unblocked this by removing the dual-orchestration; Sprint 6.5 only touches LangGraph.
- **Sprint 6.6 candidate** — custom-path MV health-check oracles.
- **Sprint 7.3 candidate** ([#65](https://github.com/jagnyesh/researchflow/issues/65)) — port the 2 deferred test files.
- **Sprint 8.5/8.6 candidates** — sparse-traffic median + exploratory portal caching.

---

# Below: Sprint 6.4 narrative (SHIPPED 2026-05-15 as b64d0d8; kept for context)

## Sprint 6.4 SHIPPED (2026-05-15 as b64d0d8) — sqlonfhir integration

Engine swap for 3 zero-row MVs the custom transpiler couldn't deliver (Sprint 6.3 verdict). Per-view-def opt-in via `runner_hint: "sqlonfhir"` — minimal blast radius, 4 custom-path MVs unchanged. Eight TDD cycles, each one RED→GREEN with its own commit.

### Empirical inputs (verified end-to-end against HAPI :5433)

| MV | Backend | Actual rows | Oracle | Delta | Materialize time |
|---|---|---:|---:|---:|---:|
| `condition_diagnoses` | sqlonfhir | 14,832 | 14,832 | 0.00% | — |
| `observation_labs` | sqlonfhir | 157,689 | 157,689 | 0.00% | **53.7s** (gate ≤60s) |
| `procedure_history` | sqlonfhir | 66,448 | 66,448 | 0.00% | — |
| `patient_simple` | custom | 366 | 366 | 0.00% | — |
| `patient_demographics` | custom | 366 | 366 | 0.00% | — |
| `condition_simple` | custom | 14,832 | 14,832 | 0.00% | — |
| `medication_requests` | custom | 20,116 | 20,116 | 0.00% | — |

All 6 pre-committed gates fired GREEN. Full HAPI-gated test suite: **35/35 PASS in ~88s**.

### What shipped

- `app/sql_on_fhir/runner/backend_dispatcher.py` (NEW) — `select_backend(view_def)` primitive that reads `runner_hint`
- `scripts/materialize_views.py` — refactored to `_materialize_via_custom()` + `_materialize_via_sqlonfhir()` per backend; type-aware DROP via `pg_class.relkind` lookup; **fix landed mid-PR**: column-collection BEFORE `sqlonfhir.evaluate()` (the library mutates view_def in-place, renaming nested `column` → `select` on forEach blocks; cycle 4 silently dropped procedure_history's 6 forEachOrNull cols; CI surfaced + fixed before merge)
- `app/sql_on_fhir/runner/hapi_db_resource_reader.py` (NEW) — reads HAPI :5433 internal schema (`hfj_resource` JOIN `hfj_res_ver`), merges `fhir_id` from `hfj_resource` into parsed JSON
- 3 view-def JSON files gained `"runner_hint": "sqlonfhir"` (condition_diagnoses, observation_labs, procedure_history)
- `app/sql_on_fhir/runner/mv_health_check.py` (NEW, ~250 lines) — same-run oracle, 5% threshold, N=3 consecutive-warn alarm filter, JSONL log to `logs/mv_health.jsonl` (gitignored)
- `app/web_ui/admin_dashboard.py` — 🩺 Materialized View health section in the Cost Telemetry tab
- 4 test files added/grown: `test_backend_dispatcher.py` (4 unit), `test_mv_health_check.py` (22 unit), `test_sqlonfhir_integration.py` (5 e2e + nested-column regression assertion), `test_custom_path_regression.py` (4 e2e)
- `tests/fixtures/mv_row_count_oracles.sql` (NEW) — single source of truth for the 3 sqlonfhir MV oracle queries with documented WHERE-clause replication + data observations
- `tests/transpiler_harness.py` — `view_exists()` rewritten to query `pg_class` with `relkind IN ('m', 'r')` so the Sprint 6.2 harness stays dispatch-agnostic across the storage-shape asymmetry
- `config/requirements.txt` + `config/requirements.lock` — `sqlonfhir==0.0.2` declared (transitive `fhirpathpy~=2.1.0` already pinned)

### Three framing notes (per Sprint 6.4 ADR)

1. **Storage shape asymmetry accepted.** Custom path writes `CREATE MATERIALIZED VIEW`, sqlonfhir path writes `CREATE TABLE + TRUNCATE + INSERT`. Trade: type-aware DROP via pg_class lookup; CONCURRENTLY refresh not available for sqlonfhir-path MVs (acceptable since batch refresh doesn't run concurrently with reads).
2. **Health-check scope is sqlonfhir-only this sprint.** The 4 custom-path MVs are covered by the Sprint 6.2 transpiler harness (48/48 tests) and cycle 7's regression test against raw resource-count anchors. Sprint 6.6 candidate filed.
3. **`runner_hint: "sqlonfhir"` is the opt-in switch.** No env var, no per-resource-type rule. The 4 working custom-path MVs declare nothing and stay on custom. If a future view-def needs the engine swap, it adds one field to its JSON and that's the entire migration.

### Surfaced + fixed mid-PR (CI catch)

- **`sqlonfhir.evaluate()` mutates view_def in-place**. Cycle 4 collected columns AFTER calling evaluate, silently dropping 6 forEachOrNull cols from procedure_history's CREATE TABLE. CI's transpiler-correctness harness (`test_schema_shape`) caught it; fixed by reordering column-collection BEFORE evaluate + added a regression assertion in the integration test.
- **`tests/transpiler_harness.py` `view_exists()` queried `pg_matviews` only**. Sprint 6.4's storage asymmetry put 3 MVs in `pg_tables` instead. Rewrote to `pg_class` with `relkind IN ('m', 'r')`.

---

# Below: previous Sprint 8.3 narrative (kept for context until Sprint 6.4 ships)

## Sprint 8.3 ready to ship (2026-05-14) — closes Sprint 8 series

Ceiling re-derivation against measured baselines. Scope-split per pre-committed grilling: ceiling derivation only; structural redesign question decoupled.

### Empirical inputs (verified manual vs aggregator within ±0.01%)

| Portal | Median | Cache hit | Old ceiling | New ceiling (median × 1.3) | Gate |
|---|---:|---:|---:|---:|:---:|
| Formal | $0.007754 | 94.88% | $0.0039 | **$0.010080** | 🟢 GREEN |
| Exploratory | $0.003540 | **0.0000%** | $0.00091 | **$0.004602** | 🟢 GREEN |

### Three framing notes (in DECISIONS.md Sprint 8.3 ADR)

1. **Semantic shift, not goalpost-moving.** Sprint 8.1's ceilings were `projection × 1.3` (cost target with tolerance). Sprint 8.3's are `measured_median × 1.3` (regression alarm against current baseline). Math identical, meaning shifts.
2. **Bursty-traffic calibration.** Medians come from `drive_qa_traffic.py` firing 30 requests in 6-7 min, within 5-min cache TTL. Sparse-traffic measurement filed as Sprint 8.5 candidate.
3. **Exploratory cache_hit_rate=0% is a real finding.** Same below-threshold class as Sprint 8.2's formal-prompt issue, not yet applied to QueryInterpreter. Filed as Sprint 8.6 candidate. Out of Sprint 8.3 scope.

### Sprint 8 series closes here

| Sprint | Verdict |
|---|---|
| 8 (2025) | Projection of 73% reduction shipped; later falsified by Sprint 8.2 |
| 8.1 (2026-05-12) | CLOSED RED — $0.009026 baseline (verified correct, cache_hit=0% protected it from aggregator bug) |
| 8.2 (2026-05-14) | SHIPPED — three failure modes diagnosed; cache_control wire fix + manual baseline $0.007754 |
| 8.4 (2026-05-14) | SHIPPED — `cache_read` double-charge fix; aggregator now matches manual ±0.01% |
| 8.3 (this PR) | SHIPPED — ceilings re-derived against measured medians; both portals GREEN |

### Next per BACKLOG

- **Sprint 6.4** ([#40](https://github.com/jagnyesh/researchflow/issues/40)) — sqlonfhir integration, 3-5 days, queued post-Sprint-8 series
- **Sprint 8.5 candidate** — sparse-traffic median measurement (filed by Sprint 8.3)
- **Sprint 8.6 candidate** — exploratory portal caching (filed by Sprint 8.3)
- **Sprint 9+** — Temporal Reasoning Engine, Complex Cohort Logic per BACKLOG Phase 2

---

## Sprint 8.4 SHIPPED (2026-05-14)

Aggregator audit complete. The 2.95× inflation Sprint 8.2 surfaced had a different root cause than Sprint 8.2 hypothesized — wire-level pull from LangSmith on 2026-05-14 revealed it.

### What Sprint 8.4 found (corrects Sprint 8.2's hypothesis)

Static-analysis hypothesis (Sprint 8.2): aggregator over-counts via parent+child summation through tag inheritance.

Wire-level reality: only LLM leaves carry both `portal:formal` AND a `thread_id` — the 6 `execute_task` chain spans have `thread_id == None` and get filtered out by `_summarize_threaded`. **Parent+child double-counting was never happening.**

The real bug: LangSmith's `Run.input_tokens` already INCLUDES `cache_read_input_tokens` (empirically verified: `total_tokens == input_tokens + output_tokens` on every observed LLM leaf). But `_run_cost_usd` charged `input_tokens * input_rate + cache_read * cache_rate`, double-billing the cache portion.

### What the fix changes

| Surface | Before | After |
|---|---|---|
| `_run_cost_usd` | `input_tok * prices["input"] + cache_read * prices["cache_read"]` | `(input_tok - cache_read) * prices["input"] + cache_read * prices["cache_read"]` |
| Sprint 8.2 30-thread median | $0.022865 (inflated) | $0.007754 (matches manual baseline within 0.01%) |
| Sprint 8.1 2026-05-12 median | $0.009026 (correct — cache_hit=0%) | $0.008997 (unchanged within 0.32% — confirms bug only fires with caching) |
| Reported `cache_hit_rate` on Sprint 8.2 traffic | 0.4869 (under-reporting ~2×) | 0.9488 (corrected via same helper) |
| Tests | 14/14 pass | 16/16 pass (2 new: wire-level fixture + schema contract) |

### Critical correction to Sprint 8.2 CLOSE ADR

The Sprint 8.2 CLOSE ADR claimed "Sprint 8.1's $0.009026 baseline came from the same aggregator and is therefore likely also inflated." **Wrong.** Sprint 8.1's traffic had `cache_hit_rate = 0.0%` everywhere; with `cache_read = 0`, the buggy formula reduces to the correct formula. Sprint 8.1's RED verdict and $0.009026 baseline are CORRECT as originally measured. DECISIONS.md Sprint 8.4 ADR documents the correction (append-only — preserves the journey).

### Next step

**Sprint 8.3** ([#47](https://github.com/jagnyesh/researchflow/issues/47)) — ceiling re-derivation + structural redesign question — is now UNBLOCKED. With trustworthy aggregator output, Sprint 8.3 can evaluate "does ResearchFlow's current model strategy clear a defensible ceiling?" against measured Sprint 8.2 baseline of $0.007754 vs the (still-valid) Sprint 8.1 baseline of $0.009026 — a real 14.1% reduction.

---

## Sprint 8.2 close (2026-05-14)

The diagnostic chain Sprint 8.1's RED verdict opened resolved into **three concurrent failure modes plus one CRITICAL surfaced bug**. Sprint 8.2 closes with corrected understanding, not a target-hit verdict — the projected 73% reduction was structurally unreachable per Task 3's projection-error diagnosis.

### Three failure modes (all diagnosed, two fixed, one structural)

| # | Failure mode | State |
|---|---|---|
| 1 | System prompt was 12 tokens, ≪ Anthropic Sonnet 1024-token / Haiku 4096-token cache threshold | Fixed (PR #45 + Task 2.1) |
| 2 | `langchain-anthropic 1.0.1`'s `_format_messages` silently drops `additional_kwargs.cache_control` when SystemMessage content is a plain string; only the content-block-array form transmits to Anthropic (6-month silent bug) | Fixed (PR #45 with wire-level test that catches the buggy shape) |
| 3 | Sprint 8 baseline projected 6 LLM calls × $0.0005/call; empirical is 2 LLM calls × $0.0045/call (3× call-count + 9× per-call cost projection error; only `requirements_agent` makes LLM calls) | Structural — projection unrecoverable at current pricing |

### Task 2.1 measured outcome (n=30/30 formal-portal threads, 2026-05-14)

Bulked `_MEDICAL_CONCEPTS_SYSTEM_PROMPT` to 5185 tiktoken / 5850 Anthropic tokens to clear Haiku 4.5's 4096-token threshold.

| Metric | Value |
|---|---:|
| Sonnet cache state across 30 threads | 1 create / 29 read / 0 miss (100% hit after warmup) |
| Haiku cache state across 30 threads | 0 create / 30 read / 0 miss (warm from Gate 0.5 calibration call) |
| **Per-thread cost — median (manual)** | **$0.007754** |
| Mean / min / max | $0.007985 / $0.006829 / $0.018356 |
| **Δ vs Sprint 8.1 $0.009026 baseline** | **−14.1%** |

The 14.1% reduction is concrete engineering value against the corrected baseline. NOT the projected 73% reduction — that target was structurally unreachable per Task 3.

### CRITICAL surfaced finding — aggregator over-counts by 2.95×

Manual per-thread cost (walking trace tree, summing `usage_metadata` from LLM child runs only): **$0.007754**.
`CostTelemetryService.get_formal_portal_cost_p50(n=30)` reports: **$0.022865**.
**Ratio: 2.95× inflation.**

This is not a Sprint 8.2 deviation; it is evidence that the aggregator in `app/services/cost_telemetry_service.py` produces incorrect numbers — likely by summing parent-trace `usage_metadata` (which LangSmith aggregates UP from LLM children) alongside the individual LLM-child counts, effectively double-counting. **Sprint 8.1's $0.009026 baseline came from the same aggregator and is therefore likely inflated too.** Filed as BLOCKING Sprint 8.4 (#46) for any future ceiling-re-derivation work.

### What shipped this sprint

PR #45 (merged 2026-05-14 as `6bf1e86`):
- `app/utils/llm_client.py` — content-block-array form for SystemMessage + module-level `_REQUIREMENTS_SYSTEM_PROMPT` (~3000 tokens, Sonnet) + initial `_MEDICAL_CONCEPTS_SYSTEM_PROMPT` (~2500 tokens, Haiku-target).
- `tests/test_prompt_optimization.py` — `TestPromptCachingWireLevel` integration test that mocks `anthropic.AsyncMessages.create` and asserts cache_control arrives in the outbound `system` kwarg.
- Archive doc `docs/sprints/archive/SPRINT_08_PROMPT_OPTIMIZATION.md` — verdict revision section naming all three failure modes.
- DECISIONS.md — "Sprint 8.2 — The 6-month silent prompt-caching bug" ADR.

This PR (`feature/sprint-8-2-task-3-remeasurement`):
- `app/utils/llm_client.py` — Haiku bulk-up to 5185 tiktoken tokens (drug classes, abbreviations, compound terms, examples 9-13).
- `DECISIONS.md` — "Sprint 8.2 CLOSE — diagnostic chain completed; corrected baseline established" ADR with discipline notes (diagnostic-first scoping, wire-level test rationale, manual verification as authoritative measure, Q1-refinement on band-violation).

### Discipline notes (what made this sprint work)

- **Diagnostic-first scoping.** Task 1 was a ~30 min binary YES/NO before any code changes. The actual diagnosis required a third branch ("prompt below threshold AND wrapper drops cache_control AND tests asserted wrong API surface"). Diagnostic-first scope prevented committing to a Task 2 fix before understanding what needed fixing.
- **Wire-level test as the structural lesson.** For fixes whose correctness depends on third-party library behavior, the test must assert the third-party API contract, not the wrapper API contract. The wrapper is the system under test for unit tests; the wire is the system under test for integration tests.
- **Manual verification supplanted aggregator at close.** Sprint 8.2 closes with manual per-thread cost ($0.007754) as authoritative, NOT aggregator output ($0.022865). For sprint-gating cost measurements, manual computation is authoritative; aggregator output is convenience reporting that must be independently verified.
- **Q1-refinement on band-violation.** Gate 0 said target 4200-4500 tokens for Haiku prompt; actual landed at 5185 (15% over). Pre-committed discipline said "halt and surface." User-pre-committed override fired ("band was cost-efficiency guideline, not load-bearing constraint; 5185 cleared cache and content was substantive not filler"). Same Q1-refinement pattern as Sprint 6.3 spike: pre-commits defend against bias, not against information.

### Next step

**Sprint 8.4** ([#46](https://github.com/jagnyesh/researchflow/issues/46), BLOCKING) — cost telemetry aggregator audit. Until the 2.95× inflation is diagnosed and corrected, every Sprint 8 series cost number is suspect.

**Sprint 8.3** ([#47](https://github.com/jagnyesh/researchflow/issues/47), depends on 8.4) — ceiling re-derivation against corrected aggregator + structural redesign question.

**Sprint 6.4** ([#40](https://github.com/jagnyesh/researchflow/issues/40)) — sqlonfhir integration; 3-5 days; runs after Sprint 8.2 close (this PR). The engine swap happens at the batch-refresh path; agents and FeasibilityService are unaffected (see "Architectural reality vs documentation" below).

## Domain terms (resolved 2026-05-11; extended 2026-05-17 by Sprint 6.5)

- **Formal Portal** — 6-agent LangGraph workflow at `app/web_ui/researcher_portal.py`. Cost metric: cost-per-request (sum across all runs in one `thread_id`).
- **Exploratory Portal** — Text2SQL NL path at `app/web_ui/research_notebook.py`. Cost metric: cost-per-query (per root trace).
- **Cost Telemetry** — read-side service aggregating LangSmith runs into per-portal medians (`app/services/cost_telemetry_service.py`).
- **Sprint gate** — pre-committed numeric criterion that fires sprint completion. For Sprint 8.1: rolling-30 cost-band on both portals. For Sprint 6.5: three-way routing divergence + LangSmith cross-correlation in `logs/sprint_6_5_gate.jsonl`.

### Differential freshness routing (Sprint 6.5, 2026-05-17)

- **FreshnessAnnotation** — three-value enum (`EXPLORATORY`, `FORMAL_DRAFT`, `FORMAL_EXTRACTION`) passed to `HybridRunner.execute(..., mode=...)`. Each mode produces a semantically distinct read: speed-merged vs batch-only, citation-anchor surfaced or not. See `app/sql_on_fhir/runner/freshness.py`.
- **FORMAL_DRAFT** — Formal Portal pre-approval cohort estimation mode. Speed-merged so the researcher sees today's reality (including new patients arriving since last batch refresh) while iterating on criteria. `batch_anchor_ts` surfaced for citation metadata in `hybrid_runner_metrics` row.
- **FORMAL_EXTRACTION** — Formal Portal post-approval extraction mode. Batch-only, no speed merge. The citability contract: re-running the same SQL against the same `batch_anchor_ts` produces a bit-identical row-set. Researcher approves a cohort *definition* (SQL/criteria), not a row-set; the row-set materializes at extraction time against the current batch.
- **batch_anchor_ts** — `MAX(refreshed_at)` across the views a HybridRunner query touched, read from `sqlonfhir.mv_refresh_metadata`. The citation anchor that makes `FORMAL_EXTRACTION` reproducible.

## Architectural reality vs documentation (surfaced by Sprint 6.3 /zoom-out)

**HybridRunner is the documented read path. Production agents bypass it today.** Sprint 6.2 shipped the Lambda Architecture runner stack (`HybridRunner` → `MaterializedViewRunner` / `SpeedLayerRunner` / `PostgresRunner`) per the design. But production agents read FHIR data through different paths:

- **`phenotype_agent`** generates SQL via `SQLGenerator` → executes via `SQLonFHIRAdapter` (bypasses Runner)
- **`extraction_agent`** executes the same SQL via `SQLonFHIRAdapter` (bypasses Runner)
- **`feasibility_service`** builds SQL via `JoinQueryBuilder` → executes via `db_client.execute_query` (bypasses Runner)
- **`HybridRunner`** is exercised by tests and the materialize_views.py batch path; not on any production read hot-path

**Implication for Sprint 6.4 (sqlonfhir integration):** the engine swap happens at the batch-refresh path (`scripts/materialize_views.py` + `postgres_runner.py` write mode). Agents and FeasibilityService are unaffected — they read MVs as Postgres tables once written, regardless of which engine wrote them.

**Implication for the future:** wiring agents through `HybridRunner` for online reads would unlock the speed-layer merge that Sprint 6.2 built. Currently it's documented architecture without a production caller. Filed as a Sprint 6.5+ candidate.

## Database topology (two Postgres instances, two roles)

| Port | Host/Docker | Role | Schema highlights |
|---|---|---|---|
| `:5432` | Host (Homebrew Postgres) | `healthcare_practice` — Synthea CSV load | `synthea.patients/conditions/...` (user-loaded, NOT used by ResearchFlow runtime today) |
| `:5433` | Docker `hapi-postgres` | HAPI FHIR's internal database | `hfj_resource`, `hfj_spidx_token` (HAPI FHIR storage) + `sqlonfhir.<view>` (the materialized views the agents read) |

`SQLonFHIRAdapter` and `MaterializedViewRunner` connect to `:5433` (`HAPI_DB_URL` env). `:5432` is dev/exploration only; no runtime code references it.

## Reference artifacts

- Sprint 8 archive: `docs/sprints/archive/SPRINT_08_PROMPT_OPTIMIZATION.md` — implementation history + the verification verdict header added 2026-05-12.
- Sprint 8.1 ADR: DECISIONS.md "Sprint 8.1 — LangSmith is source-of-truth for LLM cost; explicit portal tags promote domain language into trace data."
- Sprint 8.2: [#37](https://github.com/jagnyesh/researchflow/issues/37) (diagnostic-first cache-hit investigation).
- Cadence rule: DECISIONS.md "Workflow — PR cadence: one cohesive squash PR per sprint, opened only when the sprint's gate has fired."

---

# Below: legacy Sprint 6.2 narrative (kept for context until Sprint 8.1 ships)

## Active sprint goal (Sprint 6.2, SHIPPED 2026-05-08 as 4950e14)

Ship the real Lambda Architecture for SQL-on-FHIR (batch + speed + serving) so every "Lambda complete" claim in the README/CLAUDE/docs is verifiable from a fresh clone. Sprint 6.2 was triggered when /office-hours flagged 4 doc files claiming Lambda was complete while only 1/7 view defs materialized in production. Integrity-first: every claim either becomes true via implementation, or the claim gets rewritten.

## In progress (Sprint 6.2)

- [x] Phase 1.0 — Hand-verified anchor fixtures (3 anchors: patient_simple, patient_demographics, condition_simple) sourced from direct SQL against HAPI internal schema. Breaks the InMemoryRunner-as-oracle circularity flagged by codex review on the design doc.
- [x] Phase 1.1 (issue #9) — Transpiler correctness harness. 41 parametrized tests (later 48 after #13 added unique-index check). Built TDD-style across 7 cycles. /qa mutation testing verified signal sensitivity for Bugs 1+9 before any fix shipped.
- [x] Phase 1.2 (issues #10, #11, #12, #13, #16) — All 15 cataloged transpiler bugs fixed. 4 cataloged in design doc + 6 surfaced during /tdd implementation + Bug 13 surfaced during /qa mutation work + Bugs 14/15 surfaced during /tdd cycles. Catalog updates landed in design doc as bugs surfaced.
- [x] Phase 1.5 (issue #14) — Gate decision: PROCEED. 7/7 view defs materialize, all 3 anchors PASS sample_values, MVR.get_schema fixed, UNIQUE INDEX in place for CONCURRENTLY refresh. See DECISIONS.md Sprint 6.2 entry.
- [x] Phase 1.6 (issue #15) — Streamlit cohort verified end-to-end via HybridRunner→MaterializedViewRunner path. "Female patients with diabetes" returns 60 patients in 72.3-72.5 ms via `sqlonfhir.patient_demographics JOIN sqlonfhir.condition_simple`. (Issue body said "15" based on weekend-hack baseline; production MV path uses broader code_text ILIKE matching that catches "Diabetic retinopathy" etc. — clinically more honest. See `tests/test_phase16_cohort_e2e.py`.)
- [x] Phase 2.0 (issue #17 + #18) — Poll-based speed layer + on-demand POST /materialized_views/refresh-all (admin-gated, CONCURRENTLY).
- [x] Phase 2.1 (issue #19) — HybridRunner.execute() merge + dedup actually merges materialized + speed-layer rows.
- [x] Phase 2.3 — Sprint close. Single squash PR #24 open, all 19 CI checks green.
- [ ] Phase 2.2 — Doc rewrite (this commit is part of it). Re-enable 5 ignored Lambda test files deferred to issue #25 (CI: bring up docker-compose).

**Bonus (this session, beyond the original Sprint 6.2 scope):**

- [x] **#21** — Phenotype SQL emits gender + age predicates. Three coupled root causes: (a) dispatcher checked plural `"demographics"` but LLM emits singular `"demographic"`; (b) age clause referenced `p.birthdate` (column doesn't exist); (c) age parser only handled symbolic `>` / `<`, not natural-language "greater than 18".
- [x] **#22** — Aligned consumers (sql_generator, extraction_agent, materialized_view_runner) to the actual `patient_demographics` MV column names (`birth_date`, `family_name`, `given_name`).
- [x] **OR-match diagnoses across 3 columns** — cohort 0 → 94 on Synthea data. Synthea emits SNOMED only; phenotype SQL filter was hardcoded to `icd10_display` which is NULL for every Synthea row. Now ORs across `code_text`, `icd10_display`, `snomed_display`.
- [x] **@traceable on all 6 production agents** — closes the BACKLOG observability gap. langgraph_workflow.py calls `agent.execute_task(...)` directly (8 sites) bypassing `BaseAgent.handle_task` where the prior decorator lived.
- [x] **ApprovalBridge `qa_review` uses canonical "delivery" approval_type** — `_handle_qa_review` was firing "Unknown approval_type: qa" because `qa_approved` state flag is misnamed (it's the post-QA delivery gate).
- [x] **conftest LangSmith project pin** — pytest now writes traces to `researchflow-test`, not `researchflow-production`. Surfaced because portal traces and pytest traces were ending up in the same project.
- [x] **#26 (CRITICAL)** — Materialized-views router admin-gating + view_name allowlist. DELETE /{view_name} f-string-interpolated path param into DROP MATERIALIZED VIEW with no admin gate (only Sprint 6.1 audit-middleware default-deny, which any researcher token passes). Researcher could fire `DELETE /analytics/materialized-views/x;DROP%20TABLE%20research_requests;--` and drop any application table. 5 mutating endpoints now admin-gated, 2 path-param routes validate against `ViewDefinitionManager.list()` allowlist + `^[a-z][a-z0-9_]*$` regex. 20 new regression tests in `tests/test_materialized_views_auth.py` PROVE injection payloads return 404 and never reach `db_client.execute_query` (mock + `assert_not_called`).
- [x] **CI infra** — pytest.ini ignores HAPI/Redis-dependent tests (folded into #25 follow-up); safety CLI flag fixed in `.github/workflows/security.yml` (`--output` was repurposed to format flag in safety 3.7).

## Blockers / decisions needed

- None. PR #24 ready to merge — 19/19 CI checks green, 13 issues will auto-close on merge.

## Open follow-up issues (none merge-blocking for #24)

- **#23** — Pre-existing latent test failures (API drift in `test_sql_generation_quality.py`, non-existent class imports in `TestConservativeFactorDocumentation`, never-implemented `requirements["demographics"]` field in `test_diabetes_query_generation`).
- **#25** — CI: bring up docker-compose so service-dependent tests run (currently `--ignore`d in pytest.ini for transpiler harness, Phase 1.6, Phase 2.0a, speed-layer-runner).
- One observation_labs follow-on: WHERE clause uses `category.coding.where(system='X' and code='Y').exists()` pattern that `transpile_where_predicate` doesn't support. View materializes but returns 0 rows. Future-issue when observation analytics matter.

## What just shipped (Sprint 6.2)

Phase 1 (15 transpiler bugs, 7/7 view defs materialize, harness 48/48 PASS):

- `df2fc49` (2026-05-09) — Issue #16: Bugs 14+15 close transpiler scope, 7/7 materialize
- `d294d6f` (2026-05-09) — Issue #13: UNIQUE INDEX + Bug 9 MVR.get_schema
- `aff19c1` (2026-05-09) — Issue #12: condition_simple anchor PASS — function-call parser (Bugs 4/5/6/13)
- `2fd9e71` (2026-05-09) — Issue #11: patient_demographics anchor PASS — 7 fixes (Bugs 2/3/7/8/10/11/12)
- `57f3cd4` (2026-05-09) — Issue #10: Bug 1 — resolve id from r.fhir_id
- `749471c` (2026-05-09) — /cso fix — Bug 9 regression test added to harness
- `f5e2b0f` (2026-05-09) — Issue #9: Phase 1.1 transpiler correctness harness (TDD-built across 7 cycles)
- `c9d0a4e` (2026-05-09) — fixture: deceased_date for patient 144735 (Bug 2 half-coverage close)
- `b4d723a` (2026-05-09) — TODOS update from /plan-eng-review (decision 9A: speed-layer Redis pattern deferred)
- `27a8e19` (2026-05-09) — fixture: remove unverified country values (5A from /plan-eng-review)
- `d1fe384` (2026-05-09) — Phase 1.0: hand-verified anchor fixtures

## What just shipped (Sprint 6.1, for context — squash-merged 2026-05-08 as f931164)

Sprint 6.1 Phase 3b — encryption-at-rest (3 commits, 12 encryption tests, ready for merge):

- `1946ac5` (2026-05-07) — Issue #9: encrypt remaining 3 Tier 1 columns (inclusion_criteria, exclusion_criteria, phenotype_sql); spike outcome → `_EncryptedJSONImpl` TypeDecorator workaround for `EncryptedType(JSON)` round-trip bug
- `a7e7da7` (2026-05-07) — Issue #8: tracer bullet — `ResearchRequest.initial_request` encrypted at rest; pluggable `get_encryption_key` callable + lifespan startup gate (RuntimeError on missing/malformed key in production)
- (commit 3 = Issue #10 docs commit)

Sprint 6.1 Phase 3a — TLS enforcement (3 commits, 22 TLS tests, ready for merge):

- `d067068` (2026-05-07) — Issue #7: wire TLS middleware in lifespan + Dockerfile proxy-headers config
- `82a02ca` (2026-05-07) — Issue #7: HTTPS-redirect + HSTS middleware with ENVIRONMENT=production gate
- (commit 3 = this docs commit)

Sprint 6.1 Phase 2.3 — input validation framework (6 commits, 163 schema tests + integration test, ready for merge):

- `d65f1d2` (2026-05-04) — Issue #6: migrate Tier 2 credential models (auth, users, a2a) + framework integration test
- `e07f3f2` (2026-05-04) — Issue #5: migrate Tier 1 PHI models (research, approvals, analytics, mcp)
- `706c6b9` (2026-05-04) — Issue #5: migrate sql_on_fhir to PHIInputModel — tracer bullet
- `12bf6ff` (2026-05-04) — Issue #4: wire PHI-safe RequestValidationError handler in lifespan
- `eec5d6c` (2026-05-04) — Issue #4: framework primitives — PHIInputModel, typed primitives, bounded dict validator

Sprint 6.1 Phase 2.2 — audit pipeline (8 commits on `feature/sprint6-security-baseline`, 74 audit tests):

- `e5a094b` (2026-05-03) — wire E2E test for Issue #2 auth + explicit SQLite to bypass stale .env Postgres
- `d277723` (2026-05-03) — Finding 2 fix: gate detailed health payload behind auth (two-tier `/health/ready` + `/health/ready/detailed`)
- `a7840fa` (2026-05-03) — Finding 3 fix: correct schema versioning claim in HIPAA doc
- `1b30e5c` (2026-05-03) — Finding 1 fix: allow `/a2a/token` through middleware (bootstrap deadlock)
- `d9a595c` (2026-05-03) — Issue #3: at-least-once durability + drain supervision + `/health/ready` + `docs/HIPAA_POSTURE.md` Phase 2.2 section
- `2183ed5` (2026-05-03) — Issue #2: default-deny classifier + fail-closed pre/post pair + middleware-side JWT decode
- `744b328` (2026-05-03) — Issue #1: tracer bullet — audit one PHI route end-to-end

Earlier in Sprint 6.1:

- `c3e0280` (2026-05-02) — admin dashboard graceful handling when DB unreachable
- `803152b` (Phase 2.1) — HIPAA-compliant audit logging *schema* (table only; middleware shipped in Phase 2.2)
- `5476255` (Phase 1.4) — API rate limiting via SlowAPI
- `3e8e877` (Phase 1.3) — bcrypt password hashing
- `db8b406` (Phase 1.2) — user management CRUD endpoints
- `36062af` (Phase 1.1) — JWT authentication

## Key numbers

- Tests: LangGraph migration suite covers `test_agent_adapter.py` (24), `test_approval_bridge.py` (26), `test_langgraph_persistence.py` (14), `test_langgraph_workflow.py` (20), plus E2E. Phase 2.2 audit pipeline adds 74 tests across 8 new test files (classifier, principal, middleware, drain, drain_v2, main_wiring, resource_map, health).
- Agents: 6 production agents (Requirements, Phenotype, Calendar, Extraction, QA, Delivery)
- Workflow nodes: 15 in custom FSM (`app/orchestrator/`, production) + 17 in LangGraph FSM (`app/langchain_orchestrator/langgraph_workflow.py`, behind `USE_LANGGRAPH_WORKFLOW` flag)
- Performance: 10-100x query speedup from materialized views; <10ms Redis speed-layer latency
- SQL injection: 30 vulnerabilities fixed in Sprint 6 (parameterized queries everywhere)
- Staleness flagged: CLAUDE.md previously claimed "23-state" (actual: 17 nodes) and "12 LangSmith integration tests" (actual: 1 in `test_langsmith_integration.py`). Treat any unverified count from archived sprint reports the same way.

## Reference artifacts

- Strategic design doc: `~/.gstack/projects/jagnyesh-researchflow/jagnyesh-feature-sprint6-security-baseline-design-20260502-233911.md`
- Phase 2.2 implementation design (10 grilled decisions): `~/.gstack/projects/jagnyesh-researchflow/jagnyesh-feature-sprint6-security-baseline-phase-2-2-audit-middleware-design-20260503-180000.md`
- Test plan: `~/.gstack/projects/jagnyesh-researchflow/jagnyesh-feature-sprint6-security-baseline-eng-review-test-plan-20260503-001500.md`
- Active sprint detail: `docs/sprints/SPRINT_06_IMPLEMENTATION.md`
- HIPAA posture: `docs/HIPAA_POSTURE.md` (Phase 2.2 section drafted; Phase 3a/3b/4 sections pending)
- Open GitHub issues for Phase 2.2: #1, #2, #3 (all complete, awaiting merge)
