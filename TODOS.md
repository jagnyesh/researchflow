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

**Priority:** P2 (need a CI service container or test-doubles plan)
**Affected tests:**

- `tests/test_materialized_views_integration.py` — needs Postgres
- `tests/test_referential_integrity.py` — needs Postgres
- `tests/test_full_workflow_e2e.py` — needs `psycopg2` (also missing from `requirements-dev.txt`)
- `tests/test_sql_adapter.py` — DB-dependent
- `tests/test_redis_client.py` — needs Redis on localhost:6379
- `tests/test_speed_layer_runner.py` — needs Redis (Lambda speed layer)
- `tests/test_hybrid_runner_speed_integration.py` — needs Redis + Postgres (Lambda hybrid runner)
- `tests/sql_on_fhir/test_sql_on_fhir_integration.py` — needs HAPI FHIR + Postgres
- `tests/e2e/` (entire directory)
- `tests/integration/` (entire directory)

**Fix sketch:** Add `services:` block in `tests.yml` (Postgres + mock HAPI containers), pin `psycopg2-binary` in `requirements-dev.txt`, and gate the integration job behind `if: github.event_name == 'pull_request'` to avoid running on every push. Or split into a separate workflow (`integration.yml`) that's optional/scheduled.

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

## CRITICAL — SQL-on-FHIR pipeline unimplemented (blocks portfolio sprint)

**Priority:** P0 (blocks portfolio demo + any cohort-discovery use case)
**Component:** `app/utils/sql_generator.py`, `scripts/materialize_views.py`, `app/sql_on_fhir/`
**Discovered:** 2026-05-09 via /investigate during portfolio sprint Day 0 dry run prep
**Symptom:** Every cohort query against real Synthea data returns 0 patients. Agent stack appears to work end-to-end via LangSmith traces, but actual SQL execution layer fails silently.

**Root causes (cascading, in failure order):**

1. **`scripts/materialize_views.py` is broken** — passes FHIRPath expressions directly into Postgres `CREATE MATERIALIZED VIEW` SQL. Postgres can't parse FHIRPath. Result: 6/7 view creations fail with `syntax error at or near "/"`; 1 succeeds (`patient_simple`) but with 0 rows because the underlying SELECT also doesn't translate FHIRPath → SQL.

2. **`app/utils/sql_generator.py:35-46` hardcoded to query the (broken) materialized views.** `use_materialized_views=True` by default; the legacy `False` mode targets a `patient`/`condition`/`observation` schema that also doesn't exist in HAPI's actual table layout (`HFJ_RESOURCE`, `HFJ_RES_VER`, etc.).

3. **`SQLGenerator._build_criteria_conditions:303-340` has no `medication` concept handler.** Medication criteria (e.g., "patients on metformin") are silently dropped.

4. **`SQLGenerator` has no `encounter` concept handler; no encounter view definition exists** in `app/sql_on_fhir/view_definitions/`. Encounter-count criteria ("≥3 encounters in past 12 months") cannot be represented.

5. **`SQLGenerator.condition_code_column = "icd10_display"` (sql_generator.py:45)** — but `condition_simple.icd10_display` is populated from `code.coding.where(system='http://hl7.org/fhir/sid/icd-10-cm').display.first()`. Synthea uses SNOMED, not ICD-10. So `icd10_display` is NULL for every Synthea condition. Should query `snomed_display` or `code_text`.

**Fix scope estimate:** 1-2 weeks of real engineering, not "polish work."

**Fix sketches (in dependency order):**

a) **Replace materialize_views.py FHIRPath→SQL translator**, OR rewrite the views as raw SQL against HAPI's actual `HFJ_*` tables (skip the FHIRPath spec layer entirely). 1-3 days.

b) **Add medication concept handler** in `_build_criteria_conditions`. Should query the `medication_requests` view (which has a JSON definition but is currently broken-on-create per (a)). ~3-4 hours.

c) **Add encounter view definition + concept handler** + `_build_encounter_clause` method. ~3-4 hours.

d) **Fix the column-mapping bug** — either change `condition_code_column = "code_text"` (1 line) or add a code-system-aware fallback. ~30 min.

e) **End-to-end integration test** against real Synthea data that asserts cohort > 0 for a basic query. Required regression guard. ~2-3 hours.

**Alternative path to evaluate first (~1 hour spike):**
Switch the orchestrator to use `InMemoryRunner` (`app/sql_on_fhir/runner/in_memory_runner.py`) instead of `MaterializedViewRunner`. InMemoryRunner uses `fhirpathpy` to evaluate FHIRPath against fetched FHIR resources directly — bypasses the broken batch layer entirely. May work without the multi-week fix. Worth a 1-hour spike before committing to the deeper rewrite.

**Suggested next steps:**
1. `/office-hours` to scope the SQL-on-FHIR fix sprint properly.
2. `/plan-eng-review` once design is rough-drafted.
3. `/to-issues` to break the fix into tickets.

**Portfolio sprint impact:** Day 0 dry run is BLOCKED until at least the InMemoryRunner spike or the SQLGenerator surgery completes. Multi-week deferral.

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
