---
sprint: 6.5
date: 2026-05-17
status: shipped
supersedes: []
superseded_by: null
related: [0014-sprint-6-2-phase-1-5-lambda-finish-proceed-gate.md, 0026-sprint-6-4-sqlonfhir-integration.md, 0018-sprint-8-1-langsmith-cost-source-of-truth.md, 0023-sprint-8-4-aggregator-cache-read-double-charge.md]
---

# Sprint 6.5 — Lambda architecture differential freshness routing

Sprint 6.3's `/zoom-out` surfaced that the documented Lambda Architecture serving layer (`HybridRunner`) had **no production caller** — Sprint 6.2 shipped the runner stack but production agents bypassed it (`phenotype_agent` used `PostgresRunner` directly behind a default-off toggle; `extraction_agent` used `SQLonFHIRAdapter.execute_sql`; `feasibility_service` used raw JOIN SQL via `JoinQueryBuilder`). Sprint 6.5 wires production agents through `HybridRunner` for online reads AND introduces **three-mode differential freshness routing** so the same `HybridRunner` call site can express three semantically distinct read intents.

## Three modes (FreshnessAnnotation enum)

| Mode | Speed merge | batch_anchor_ts surfaced | Caller |
|---|:---:|:---:|---|
| `EXPLORATORY` | ✅ | not surfaced | Exploratory Portal :8501 (Text2SQL NL) |
| `FORMAL_DRAFT` | ✅ | ✅ | Formal Portal pre-approval cohort estimation |
| `FORMAL_EXTRACTION` | ❌ | ✅ | Formal Portal post-approval extraction |

Researcher approves a cohort **definition** (SQL/criteria), not a row-set. The row-set materializes at extraction time against the current batch, anchored to `batch_anchor_ts`. Re-running the same SQL against the same `batch_anchor_ts` is bit-identical — citable.

## Eight grilling decisions locked pre-implementation

| Decision | Choice | Why |
|---|---|---|
| Scope framing | Option G — portfolio scope, ~3-4 days | Audience: senior PM/TPM in agentic-AI / data platforms; architectural exercise matters more than clinical realism |
| Writer complexity | Thin mutator + `--cohort` presets (t2dm, hypertension) | Architecture proof needs ONE write; clinical realism is Sprint 6.5b-portfolio-polish |
| Mode dimension | P2 — 3 modes (EXPLORATORY / FORMAL_DRAFT / FORMAL_EXTRACTION) | Maps to researcher-facing portals AND exposes the pre/post-approval split at the enum level |
| FORMAL_EXTRACTION semantics | 2b — extraction-time batch anchor | No regulatory driver for approval-time snapshot; 2b is simpler and still citable via `batch_anchor_ts` |
| `batch_anchor_ts` source | Tiny `mv_refresh_metadata` table in HAPI :5433 | Cross-DB writes from `materialize_views.py` would require schema migration in the app DB + injecting an app-DB dependency into `HybridRunner`; same-DB is cheaper |
| Metrics destination | B — Postgres + LangSmith metadata tags | Cross-sprint cost-telemetry compounding: Sprint 8.1's tab inherits `hybrid_runner.mode` as a span attribute without joining to Postgres |
| Dashboard pollution | `suppress_metrics=True` parameter | "Don't write what you'll filter" — dashboard polling would otherwise dominate the metrics table and pollute aggregations |
| Gate criterion | Three-way routing divergence + LangSmith cross-correlation | Pre-commits the architecture's load-bearing claim to a concrete empirical test rather than "plumbing reachable" |

## Per-phase commit ledger

| Phase | Commit | Outcome |
|---|---|---|
| 1 — Synthetic FHIR writer + `mv_refresh_metadata` table (#68) | `f3f21d7` | `scripts/drive_fhir_traffic.py` (one-shot + `--daemon`, 2 SNOMED presets); table in HAPI :5433; `materialize_views.py` records refresh events. Surfaced + fixed: writer-fixture cleanup needed to avoid breaking Sprint 6.4 regression tests. |
| 2A cycle 1 — `FreshnessAnnotation` enum (#69) | `7424621` | 3-value enum tracer bullet. ADR note: sibling-getter pattern chosen over tuple return for backward compat — see below. |
| 2A cycle 2 — `mode=EXPLORATORY` routes to speed-merge | `564f79d` | `HybridRunner.execute(..., mode=...)` parameter added; default EXPLORATORY preserves existing behavior. |
| 2A cycle 3 — `FORMAL_DRAFT` merges + `batch_anchor_ts` accessible | `aa99fc6` | `HybridRunner.get_last_batch_anchor_ts()` sibling getter; populated from `mv_refresh_metadata`. |
| 2A cycle 4 — `FORMAL_EXTRACTION` skips speed-merge | `c1e2ce3` | Citability contract: re-running the same query against the same `batch_anchor_ts` is bit-identical. |
| 2A cycle 5 — Postgres metric row written | `356dde3` | `sqlonfhir.hybrid_runner_metrics` table + `_record_metric()`. **5↔7 swap during grilling** — original ordering had suppress before write, making suppress trivially-passing. |
| 2A cycle 6 — `batch_anchor_ts` MAX across multiple views | `b5ecb32` | `get_batch_anchor_ts_for_views(view_names: List[str])` public method; forward-compatible with Sprint 6.5b multi-view feasibility wiring. |
| 2A cycle 7 — `suppress_metrics=True` skips writes | `863c03c` | Both-branches falsifiable test (suppress=True → no write; suppress=False → row appears). |
| 2A cycle 8 — LangSmith metadata + trace_id correlation | `f4f4416` | `@traceable` on `HybridRunner.execute()`; `langsmith.RunTree.add_metadata()` mirrors Postgres columns. Cross-sprint compounding with Sprint 8.1 Cost Telemetry tab. |
| **Retro refactor 1** — `HybridRunnerMetric` dataclass | `e196a81` | `/improve-codebase-architecture` candidate: replace hand-mirrored two-sink emission with one dataclass + two adapters. Eliminates drift risk Cycle 8 was designed to catch. |
| **Retro refactor 2** — Shared fixtures → `conftest.py` | `2b563e0` | Same fixtures had been duplicated in 2 test files; consolidated. |
| /qa fix — `test_mv_refresh_metadata` DSN | `3e4b3e5` | Test used raw `asyncpg.connect(os.getenv("HAPI_DB_URL"))` but env value has `postgresql+asyncpg://` prefix asyncpg can't parse. Same pattern bit `materialize_views.py` later. |
| 2B-1 — `phenotype_agent` wired through HybridRunner | `f71ac4e` | Toggle `use_view_definitions` flipped to True (Sprint 6.2-era "ViewDefinition broken" comment was stale per empirical pre-flight); `HybridRunner.execute(mode=FORMAL_DRAFT, caller='phenotype_agent')` at 2 call sites. |
| 2B-2 — `extraction_agent` deferred to #71 | `7f87662` | Audit of all 4 `sql_adapter.execute_sql` sites found zero clean single-view view-def candidates. Honest scope close: `extraction_agent` + `feasibility_service` ship together in Sprint 6.5b via `execute_sql_with_view_hints`. |
| 2B-3 — Focused integration test for wiring | `4140a34` | Path pivot during 2B-3: `test_nlp_to_sql_workflow.py` proved LLM-judgment-flaky (issue #75); focused test in `test_hybrid_runner_freshness.py::TestPhenotypeAgentWiring` drives `phenotype_agent` directly. Bounded scope, deterministic. |
| 4 — Gate + `materialize_views.py` DSN fix | `dbb016c` | `scripts/sprint_6_5_gate.py` runs end-to-end against real HAPI/Redis/LangSmith; 8/8 assertions pass; `logs/sprint_6_5_gate.jsonl` captures evidence. |
| 7 — Close (this commit) | tbd | ADR + CONTEXT.md domain terms + INDEX.md entry |

## Empirical gate results (2026-05-17 run)

| Assertion | Expected | Observed |
|---|---|---|
| `redis_speed_layer_seeded` | 5 patient keys after FHIRSubscriptionService cycle | present |
| `exploratory_row_count` | N+5 = 47 (speed-merged t2dm conditions) | 47 |
| `formal_draft_row_count` | N+5 = 47 (speed-merged with metadata) | 47 |
| `formal_draft_freshness` | 0 ≤ delta < 90s | 1s |
| `formal_extraction_count` | N = 42 (batch-only, no merge) | 42 |
| `formal_extraction_anchor` | matches mv_refresh_metadata MAX | exact match |
| `langsmith_cross_correlation` | trace_id resolves; metadata mirrors Postgres | exact match |
| **Total blockers** | **0** | **0** |

Numbers tell a coherent story: 42 baseline t2dm conditions in Synthea + 5 new from writer = 47 visible to EXPLORATORY/FORMAL_DRAFT (speed-merged); only 42 visible to FORMAL_EXTRACTION (batch-only). The MV refresh ran 1 second before the gate, so freshness_delta=1s. LangSmith metadata for mode/freshness/speed_layer_hit matches Postgres exactly — the cross-correlation that justified picking option B over A in D4 grilling works.

## Surfaced + filed during sprint (non-blockers)

- **#71 expanded scope** — `feasibility_service` was the original deferral target; Sprint 6.5 Phase 2B-2 audit added `extraction_agent` to the same scope. Both have the multi-view JOIN + raw-SQL shape that doesn't fit `HybridRunner.execute(view_definition, ...)`; both need `execute_sql_with_view_hints()` designed together. The 4 deferral sites in `extraction_agent.py` have inline comments referencing #71.
- **#74** — `tests/test_phase20a_speed_layer.py::test_polling_caches_patients_by_fhir_id` flakes when HAPI has soft-deleted Patients. Surfaced during /qa; production code (`FHIRSubscriptionService.set_fhir_resource`) is correct (keys by `fhir_id` not bigint `res_id`); the test's setup query doesn't filter `res_deleted_at IS NULL`, so cleanup of synthetic patients elsewhere makes the test pick a deleted target. Test hygiene only.
- **#75** — `tests/test_nlp_to_sql_workflow.py` is LLM-judgment-flaky for the whole file. Surfaced during 2B-3 path (i) attempt. /diagnose root-causing showed `requirements_agent` returning `ready_for_submission=False` for hardcoded test prompts; LLM judgment shifts across Anthropic model behavior changes. Architectural recommendation: pre-write `RequirementsData` rows or mock `requirements_agent` in workflow tests. Sprint 7.2's "verified working" claim was likely a one-shot LLM judgment that re-runs don't reproduce.

## Architectural decisions worth pulling out (Sprint 6.5c candidates)

### Sibling-getter pattern over tuple return

`HybridRunner.execute()` keeps its `List[Dict]` return type. `batch_anchor_ts` surfaces via `get_last_batch_anchor_ts()` — a sibling getter mirroring `get_last_executed_sql()` at `hybrid_runner.py:~290`. Chosen over breaking-change tuple return because Phase 2B doesn't need `batch_anchor_ts` at agent call time — only the gate does. If a future sprint wires **staleness-aware agent reasoning** (e.g., `phenotype_agent` flagging borderline cohorts as "estimate is N ± confidence based on Xs of staleness"), revisit return shape — likely to an `ExecutionResult` dataclass with `rows`, `batch_anchor_ts`, `speed_layer_hit`, `freshness_delta_seconds` returned directly from `execute()`.

Filed implicitly as a Sprint 6.5c candidate; not a current Sprint 6.5 deliverable.

### `HybridRunnerMetricsRecorder` extraction (deferred)

`HybridRunner` now mixes two responsibilities at ~600 LOC: *executing* queries (batch + speed merge + mode routing) and *observing* queries (table management, Postgres INSERT, LangSmith bridge). The observation surface is ~100 LOC. Could extract as `HybridRunnerMetricsRecorder` module — but only `HybridRunner` uses the recorder today ("one adapter = hypothetical seam, two adapters = real seam" per LANGUAGE.md). Defer until a second caller emerges (e.g., Sprint 6.5b feasibility multi-view metrics with a different schema). In-code marker at the recorder code (`hybrid_runner.py:_record_metric`) preserves the consideration for future-me.

## Meta-pattern instances this sprint (multiple fired)

The project's "what would have to be true for this verdict to be wrong?" defense (`docs/decisions/0000-meta-recurring-workflow-pattern.md`) fired several times in Sprint 6.5:

1. **Path A pre-flight check (Phase 2B-1 entry).** Originally planned Phase 2B as "mechanical 2-line swap at phenotype_agent.py:263 + :517." Grilling assumed `postgres_runner.execute()` was the active code path. Empirical check before commitment showed it was behind a `use_view_definitions=False` toggle (Sprint 6.2-era). 30-min pre-flight saved a half-day of misdirected work.
2. **Phase 2B-2 audit reframed scope** — initial grilling assumed path (a) [refactor single-view sites to view_def] would let me wire ~half of extraction_agent's sites. Audit found zero clean single-view sites. Honest scope close (deferred to #71) instead of speculatively forcing path (b) [add `execute_sql_with_view_hints`] mid-sprint.
3. **/qa initial finding was wrong** — flagged `FHIRSubscriptionService` keys-by-res_id as HIGH Phase 4 blocker based on a test's misleading failure message. Empirical verification (query `hfj_resource` directly, inspect Redis keys post-polling) showed production code is correct; the test's setup ignores soft-deleted patients. Filed as #74 with self-review note about jumping to conclusion from framework's verdict. Same pattern as Sprint 7.2 Phase 1 close.
4. **2B-3 path pivot from (i) to (ii)** — originally chose `test_nlp_to_sql_workflow.py` as integration test seam under assumption "Sprint 7.2 verified it works." /diagnose found the file is LLM-judgment-flaky; the Sprint 7.2 verification was a one-shot LLM judgment. Pivoted to focused-test approach (ii) at agent boundary rather than fix the broader infrastructure mid-sprint.

Each instance saved meaningful misdirection cost. The pattern continues to deliver asymmetric ROI; the discipline is durable.

## What Sprint 6.5 closes (vs what stays open)

**Closed:**
- "Documented Lambda Architecture has no production caller" for `phenotype_agent`
- `HybridRunner.execute(mode=FreshnessAnnotation, caller=str, suppress_metrics=bool)` is the production API
- `sqlonfhir.hybrid_runner_metrics` + `sqlonfhir.mv_refresh_metadata` tables exist in HAPI :5433
- LangSmith span tags + Postgres rows are dual sinks for the same metric data (cross-sprint compounding with Sprint 8.1)
- Gate script provides reproducible empirical evidence

**Open (filed):**
- `extraction_agent` + `feasibility_service` deferred to Sprint 6.5b (#71)
- Admin dashboard "Differential Freshness Routing" tab (#73, portfolio-only — does not ship in Sprint 6.5 close)
- Test-design fragility in `test_nlp_to_sql_workflow.py` (#75)

## Reference artifacts

- Issues: tracker #67 + phase issues #68 #69 #70 #72 + portfolio #73 + deferred #71 + surfaced-during-sprint #74 #75
- Gate evidence: `logs/sprint_6_5_gate.jsonl` (gitignored — local artifact)
- Empirical verification queries: `tests/test_hybrid_runner_freshness.py::TestPhenotypeAgentWiring`
