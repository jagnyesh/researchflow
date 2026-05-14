# ResearchFlow — Current State

**Sprint:** 8.1 (Prompt Optimization Verification) — **CLOSED 2026-05-12 with RED verdict per pre-committed D8 failure-mode rule.** Verification was the deliverable; the verdict is the artifact.
**Branch:** `feature/sprint-8-1-prompt-cost-telemetry` (6 commits ahead of main; squash PR opening now).
**Recently shipped:** Sprint 6.2 squash-merged 2026-05-08 as `4950e14`. CI follow-on #27 squash-merged 2026-05-11 as `8339a12`.
**Overall progress:** Sprint 6.1 SHIPPED 2026-05-08, Sprint 6.2 SHIPPED 2026-05-08, CI #25 SHIPPED 2026-05-11, Sprint 8.1 CLOSED 2026-05-12 (RED). ~13/22 sprints overall.
**Last updated:** 2026-05-12

## Sprint 8.1 verdict (closed 2026-05-12)

Sprint 8 was the optimization sprint (shipped 2025 on `feature/langchain-agents-migration`). Sprint 8.1 was the verification sprint. **The verification ran exactly as designed and produced its verdict; the verdict happened to be RED.** That is the point of the pre-committed D8 rule — the sprint succeeded in measuring, not in achieving.

### Measured (n=30/30 on each portal, zero errors, 6.4 min wall-clock)

| Portal | Median | Band ceiling | Ratio | Cache hit | Gate |
|---|---:|---:|---:|---:|:---:|
| Formal | **$0.009026** | $0.0039 | **3.01× projected** | **0.0%** | 🔴 |
| Exploratory | **$0.003413** | $0.00091 | **4.88× projected** | **0.0%** | 🔴 |

### What the verdict says

The 73% cost-reduction projection from Sprint 8 was built primarily on prompt caching (Optimizations 1-3). Observed `cache_hit_rate = 0.0%` on every run is the smoking gun: either the `cache_control` blocks aren't being sent on outbound Anthropic API requests, or they're being sent but the `cache_read_input_tokens` aren't being captured by the cost-telemetry aggregator. **These two hypotheses have ~10× different implementation scope.** Sprint 8.2 disambiguates them in Task 1 before scoping any fix.

### What shipped this sprint (verification artifacts, not optimizations)

- `app/services/cost_telemetry_service.py` — LangSmith-as-source-of-truth aggregator (formal: per-thread; exploratory: per-root-trace). See DECISIONS.md Sprint 8.1 ADR.
- `app/web_ui/admin_dashboard.py` — new "💰 Cost Telemetry" tab with two portal panels + gate-status badges.
- `scripts/drive_qa_traffic.py` — synthetic-traffic harness for filling the rolling-30 window (re-runnable for Sprint 8.2 verification).
- `portal:formal` / `portal:exploratory` tags on 8 `@traceable` sites (6 agents + `query_interpreter` + `feasibility_service`).
- `tests/test_cost_telemetry_service.py` (14 tests) + `tests/test_portal_tags.py` (10 tests) + 3 bitrot fixes in previously-ignored test files. Tests partition extended with `requires_api_key` marker.

### Next step

**Sprint 8.2** ([#37](https://github.com/jagnyesh/researchflow/issues/37)) — diagnostic-first investigation of the zero-cache-hit root cause. Filed before this PR opens so the next-step trail is durable. Task 1 (~30 min) pulls one LangSmith trace and inspects the outbound payload; the YES/NO answer gates Task 2 scope.

## Domain terms (resolved 2026-05-11, unchanged)

- **Formal Portal** — 6-agent LangGraph workflow at `app/web_ui/researcher_portal.py`. Cost metric: cost-per-request (sum across all runs in one `thread_id`).
- **Exploratory Portal** — Text2SQL NL path at `app/web_ui/research_notebook.py`. Cost metric: cost-per-query (per root trace).
- **Cost Telemetry** — read-side service aggregating LangSmith runs into per-portal medians (`app/services/cost_telemetry_service.py`).
- **Sprint gate** — pre-committed numeric criterion that fires sprint completion. For Sprint 8.1: rolling-30 cost-band on both portals.

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
