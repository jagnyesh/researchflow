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
