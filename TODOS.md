# TODOS

Tracks pre-existing regressions surfaced during Sprint 6.1's CI cleanup. Each entry should land its own follow-up sprint or PR; do not silently expand the `--ignore` list in `pyproject.toml`.

## Sprint 7 — LangGraph workflow regressions

**Priority:** P1
**Component:** `app/langchain_orchestrator/`
**Symptom:** `'coroutine' object is not subscriptable` errors and FSM-state assertion mismatches (e.g., `'requirements_review' == 'requirements_gathering'`)
**Affected tests** (currently `--ignore`d in `pyproject.toml`):

- `tests/workflows/test_langgraph_workflow.py` — TestNodeHandlers, TestConditionalRouting, TestWorkflowExecution, TestErrorHandling, TestGraphConstruction
- `tests/test_langgraph_persistence.py` — checkpointer concurrency, thread isolation, state persistence
- `tests/test_preview_extraction_workflow.py` — preview QA + workflow transitions
- `tests/test_workflow_incomplete_requirements.py` — approval state machine
- `tests/test_approval_bridge.py` — bridge initialization + modification handlers
- `tests/test_dashboard_tabs.py` — Sprint 7 dashboard refactor regressions
- `tests/test_phase2_parallel.py`
- `tests/test_agent_comparison.py`

**Root cause hypothesis:** Sprint 7 finalized the LangGraph migration via singleton checkpointer + LangSmith tracing. The test suite was not updated to match the final FSM node names or async invocation pattern. Symptoms suggest the tests were authored against an earlier draft of the workflow.

**Fix sketch:**
1. Read the current `langgraph_workflow.py` FSM definition. Update test assertions to match real node/state names.
2. For `'coroutine' object is not subscriptable`: tests are likely calling `await graph.ainvoke(state)` then indexing the return synchronously. Either await the result or use the proper invocation pattern.
3. Re-enable each test module by removing its `--ignore` line in `pyproject.toml`. Verify in isolation, then with the rest of the suite.

---

## Sprint 8 prep — Multi-LLM client + prompt caching scaffolding

**Priority:** P2 (deferred until Sprint 8 starts)
**Component:** `app/utils/llm_client.py`, multi-provider scaffolding
**Symptom:** Tests reference unimplemented `MultiLLMClient` API surface and prompt-cache flags
**Affected tests:**

- `tests/test_multi_llm_client.py` — TestCompleteMethod, TestExtractStructuredJSON, TestModelIdentifierSelection, TestMultiLLMClientInitialization, TestAgentIntegration
- `tests/test_prompt_optimization.py` — TestPromptCachingEnabled

These are scaffolding for the Sprint 8 prompt-optimization work (BACKLOG.md: 73% projected cost reduction). They were checked in early. Re-enable in lockstep with Sprint 8 implementation.

---

## Tests requiring external services in CI

**Status:** Plan landed via `/plan-eng-review` on 2026-05-11. Tracked as issue #25 (PR-A + PR-B). See `~/.gstack/projects/jagnyesh-researchflow/jagnyesh-main-eng-review-test-plan-*.md` for the full review.

**Priority:** P2 (in-progress)
**Affected tests:**

- `tests/test_materialized_views_integration.py` — needs Postgres (PR-B)
- `tests/test_referential_integrity.py` — needs Postgres (PR-B)
- `tests/test_full_workflow_e2e.py` — needs `psycopg2` (also missing from `requirements-dev.txt`) (PR-B)
- `tests/test_sql_adapter.py` — DB-dependent (PR-B)
- `tests/test_redis_client.py` — needs Redis on localhost:6379 (PR-B)
- `tests/test_speed_layer_runner.py` — needs Redis (Lambda speed layer) (PR-A)
- `tests/test_hybrid_runner_speed_integration.py` — needs Redis + Postgres (PR-B)
- `tests/sql_on_fhir/test_sql_on_fhir_integration.py` — needs HAPI FHIR + Postgres (PR-B)
- `tests/test_transpiler_correctness.py` — Sprint 6.2 harness (PR-A)
- `tests/test_phase16_cohort_e2e.py` — Sprint 6.2 cohort e2e (PR-A)
- `tests/test_phase20a_speed_layer.py` — Sprint 6.2 speed-layer (PR-A)
- `tests/integration/` (entire directory) (PR-A — CQ1 fold-in, existing integration-test job is silently a no-op)
- `tests/e2e/` (entire directory) — out of scope (separate workflow)

**Resolution plan (decided in /plan-eng-review 2026-05-11):**
1. **PR-A**: docker compose up -d --wait + pg_dump fixture + 4 PR-A test files + fold in dead integration-test job (CQ1).
2. **PR-B**: re-enable older 7 service-dependent ignores, debug any drift surfaced.
3. **TODO follow-on**: nightly Synthea-regen workflow (deferred — see entry below).

---

## Nightly Synthea regen workflow (post-#25)

**Priority:** P3 (deferred — file once PR-A lands)

**What:** Scheduled GH Actions workflow runs Synthea, loads a fresh HAPI, pg_dumps, and opens a PR with updated fixture (`tests/fixtures/hapi_seed.sql.gz` + `hapi_seed.meta.json`) and any necessary updates to `tests/fixtures/transpiler_expected_outputs.py`.

**Why:** Catches Synthea CLI drift and module/version changes before they surface in a developer PR. Keeps the dump-regeneration muscle alive — if rotation never runs, the first manual attempt rediscovers the procedure from scratch.

**Pros:**
- Future-proofs dump rotation.
- Surfaces upstream Synthea changes as PRs (visible review, not silent drift).
- May find transpiler regressions earlier (new data shapes = new edge cases).

**Cons:**
- Real eng effort (~4–6h to write + test the workflow).
- Adds a recurring CI cost (one workflow run/day).
- Could produce noisy PRs if Synthea is non-deterministic at the patient level.

**Context:** Surfaced in `/plan-eng-review` D1 as option D's nightly half. User picked option B (plain git + manual rotation), so the LFS half doesn't apply; the nightly half stands alone. Worth capturing because dump rotation will eventually need a procedure and the rebuilt artifact + the changelog of expected-counts deltas is the right shape.

**Depends on:** PR-A landing (this provides the rotation target).

**Fix sketch:**
1. Add `.github/workflows/synthea-regen.yml` with `schedule: cron: '0 4 * * *'`.
2. Steps: run Synthea container (existing profile in compose.yml), wait for HAPI healthy, run `scripts/load_synthea_to_hapi.py`, `pg_dump -Fc -Z 9 hapi_db > hapi_seed.sql.gz`, write meta.json with hapi_tag + counts + generated_at, open PR via `gh pr create`.
3. PR description includes diff in patient_count / condition_count / observation_count from the previous fixture.

---

## Quarterly pytest.ini ignore-list audit

**Priority:** P3 (deferred — first audit due Sprint 9 timeframe)

**What:** A quarterly cleanup pass that re-verifies each remaining `--ignore` line in `pytest.ini`: is the test still relevant? Still ignored for the original reason? Or can it be deleted / fixed / re-enabled?

**Why:** The ignore-list is the exact debt-accrual pattern #25 was filed to attack. Even after PR-A + PR-B remove ~11 entries, ~16 will remain across Sprint 7 / Sprint 8 / LLM-quality buckets. Without a recurring forcing function, the chain grows monotonically (its prior trajectory: 0 → 27 over ~12 months).

**Pros:**
- Caps growth with a cheap forcing function.
- Surfaces stale entries that don't fit any of the existing per-bucket TODOs.
- Each audit takes ~30 min; high value per hour.

**Cons:**
- One more recurring task.
- Easy to skip; needs calendar discipline.

**Context:** Surfaced in `/plan-eng-review` on 2026-05-11. The per-bucket TODOs (Sprint 7, Sprint 8 prep, LLM-quality) already exist but didn't keep the list under control — they tracked entries but didn't drive removals. This meta-task is the missing forcing function.

**Depends on:** PR-A + PR-B landing.

**Fix sketch:** Per quarter: open the file, walk each `--ignore` entry, decide remove-now / keep-tracking-with-this-issue / delete-test-file. Update the per-bucket TODO entries. Log the audit date in this section.

---

## LLM-quality tests with drifted expectations or missing API key

**Priority:** P2
**Affected tests:**

- `tests/test_text2sql.py` — query interpreter assertions (`assert 'observation_labs' in ['patient_demographics']`)
- `tests/test_nlp_to_sql_workflow.py` — natural-language → SQL output
- `tests/test_case_sensitive_count_regression.py` — case-sensitivity tests with hardcoded expected outputs
- `tests/sql_on_fhir/test_sql_generation_quality.py` — query quality assertions
- `tests/agents/test_phenotype_agent_filtering.py` — phenotype filtering with LLM
- `tests/agents/test_phenotype_agent_with_conditions.py` — LLM-driven assertion drift

**Fix sketch:** Either (a) provide `ANTHROPIC_API_KEY` as a CI secret + accept the API cost, OR (b) refactor these to use deterministic LLM mocks (e.g., `responses` library or the existing test-double fixtures), OR (c) move them to a separate `eval` job that runs nightly rather than on every PR.

---

## Sprint 6.2 (lambda-finish) — Phase 2.1 design decision RESOLVED

**Priority:** Done as of issue #19 (commit pending)

**Decision 9A: HSET keyed by `fhir:<type>:<id>`** (option a from the original deferral). RedisClient already implements this; FHIRSubscriptionService writes via `set_fhir_resource(type, id, data)` which stores as `fhir:<type>:<id>` keys. SpeedLayerRunner.scan_recent_resources reads them. HybridRunner._merge_batch_and_speed_results dedups by `id` field of the extracted rows.

**Why HSET wins for this architecture:**
- The dedup logic is by FHIR id, which the cache key already is. No need for time-range scans.
- Sorted-set-with-versionId-score (option b) would be useful if we needed "give me all resources updated since timestamp T" range queries. We don't — the polling service already filters by `res_updated > since` at the SQL level.
- Cache eviction by 24hr TTL is per-key with HSET; sorted-set TTL is all-or-nothing. HSET fits our per-resource freshness semantics.

**Refactor candidate flagged in #19:** HybridRunner._extract_rows_from_resources reaches into InMemoryRunner's private `_transform_resource` method. Long-term, that transformation logic should be a module-level function shared by both runners. Not blocking; cosmetic.

**Surfaced by:** /plan-eng-review on feature/lambda-finish, 2026-05-09 (Q9). Resolved in issue #19.

---

## CI infrastructure debt resolved in PR #8

**Priority:** Done as of PR #8 (`feature/sprint6-security-baseline` → `main`)

- Bumped `actions/upload-artifact@v3` → `@v4` (5 places)
- Bumped `actions/setup-python@v4` → `@v5`
- Bumped `github/codeql-action/{init,autobuild,analyze}@v2` → `@v3`
- Bumped `codecov/codecov-action@v3` → `@v4`
- Dropped Python 3.9 + 3.10 from test matrix (`pyproject.toml` requires `>=3.11,<3.13`)
- Pinned `black==25.9.0` to match pre-commit config (resolved 3-way version mismatch)
- Pinned `fakeredis>=2.20.0` (was missing, broke audit test collection)
- Added `.gitleaks.toml` allowlisting `.secrets.baseline` (gitleaks vs detect-secrets conflict)
- Made `validate-diagrams` non-blocking (Ubuntu apt plantuml is older than the syntax used)
- Added `import traceback` in `phenotype_agent.py:540` (F821) + removed unused `_checkpointer_mutex` global (F824)
