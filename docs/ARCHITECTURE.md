# Architecture

This reference describes the code on `main` as of 2026-11-09. [`CONTEXT.md`](../CONTEXT.md) defines the project's terms, such as Formal Portal, Exploratory Portal, `FreshnessAnnotation`, and `batch_anchor_ts`.

## Components and ports

| Component | Port | Code or Compose service |
|---|---|---|
| Exploratory portal, a chat | 8501 | `app/web_ui/research_notebook.py` |
| Formal portal, a form | 8502 | `app/web_ui/researcher_portal.py` |
| Admin dashboard, for approvals | 8503 | `app/web_ui/admin_dashboard.py` |
| API | 8000 | `app/main.py` |
| HAPI FHIR server | 8081 | `hapi-fhir`, image `hapiproject/hapi:v8.8.0` |
| HAPI Postgres, with the `sqlonfhir` schema | 5433 | `hapi-db` |
| Redis for the speed layer | 6379 | `redis` |
| Redis for the audit queue | 6380 | `redis-audit` |

The application database defaults to SQLite at `./dev.db`. `app/database/models.py` defines 10 tables (`grep -c __tablename__ app/database/models.py`). [`CONTEXT.md`](../CONTEXT.md) describes the two Postgres instances under "Database topology".

Three older views of the system disagree with this doc in places. Follow this doc.

- The picture at [`images/architecture-overview.png`](images/architecture-overview.png) and the [interactive diagram](https://jagnyesh.github.io/researchflow/architecture.html) predate Sprint 7.2. They show six agents, a calendar step, and the retired agent-to-agent orchestrator.
- [`05-24architecturereview.md`](architecture/05-24architecturereview.md) and the earlier [05-15 snapshot](architecture/05-15architecturereview.md) predate Sprint 6.7.

## Where the LLM is called

| Call site | Model | Purpose |
|---|---|---|
| `RequirementsAgent`, through `LLMClient.extract_requirements` | `claude-sonnet-4-6` | Extract the cohort specification from the request |
| `RequirementsAgent`, through `LLMClient.extract_medical_concepts_batch` | `claude-haiku-4-5-20251001` | Extract the medical concepts from a list of criteria in one call, once for the inclusions and once for the exclusions. `extract_medical_concepts` retries a criterion that comes back empty |
| `SQLSynthesizer.synthesize` in `app/services/sql_synthesis.py` | `claude-sonnet-4-6` | Write the exploratory SQL |
| `ConversationManager` in `app/services/conversation_manager.py` | `claude-sonnet-4-6` | Classify a chat message that the patterns cannot classify |

`app/agents/` holds five `BaseAgent` subclasses: `RequirementsAgent`, `PhenotypeValidationAgent`, `DataExtractionAgent`, `QualityAssuranceAgent`, and `DeliveryAgent`. The last four make no LLM call.

### Prompt caching and cost

- The Sonnet system prompt is about 3,000 tokens, and the Haiku prompt is about 5,185. Both sit above the thresholds in `_ANTHROPIC_CACHE_THRESHOLDS`: 1,024 tokens for Sonnet and 4,096 for Haiku.
- The formal portal's median cost is $0.007754 per request over 30 threads, with a 94.88% cache hit rate. The regression ceiling is $0.010080 ([ADR 0025](decisions/0025-sprint-8-3-cost-ceilings-re-derived.md)). The 05-24 review attributes 94.88% to the Sonnet prompt and 100% to the Haiku prompt, after warmup.
- The exploratory portal's median cost is $0.003586 per query over 30 root traces, with a 95% cache hit rate. The ceiling is $0.004661 ([ADR 0028](decisions/0028-sprint-6-7-exploratory-llm-sql-synthesis.md)).
- Both measurements used bursty traffic from [`scripts/drive_qa_traffic.py`](../scripts/drive_qa_traffic.py): 30 formal requests in 6 to 7 minutes, and 30 exploratory queries in 120 seconds. With gaps over 5 minutes between requests, the median moves toward the cache-create cost. That measurement is the Sprint 8.5 candidate.
- Each of the five agents has one `@traceable` decorator for LangSmith. The tags `portal:formal` and `portal:exploratory` let `CostTelemetryService` report a median for each portal.

## Formal workflow graph

`FullWorkflow` in `app/langchain_orchestrator/langgraph_workflow.py` builds a LangGraph `StateGraph` with 16 nodes (`grep -c "graph.add_node" app/langchain_orchestrator/langgraph_workflow.py`). Each router is a plain function of the workflow state. The [README](../README.md#formal-portal-rules-write-the-sql-and-a-reviewer-approves-it) lists the steps in order, and `_build_graph` in the same file is the list of nodes and edges.

- The four terminal nodes are `complete`, `not_feasible`, `qa_failed`, and `human_review`. No router returns `human_review`.
- The preview check passes when the cohort size is within 50% of the estimate. For an estimate under 10 patients, the tolerance is 5 patients.
- The preview is not de-identified. The full extraction is de-identified by default. With `phi_level` set to `limited_dataset`, the step removes only `patient_name` and `ssn`, columns that no view emits. Dates, source ids, `family_name`, and `given_name` stay, and the QA check fails a delivery that holds a name column. With `identified`, the step removes nothing.
- `_extract_data_element` reads at most the first 1,000 patient ids.

## Approval gates

The graph compiles with `interrupt_after` on four review nodes. Each node writes a pending row to the `approvals` table, and the run stops there.

| Review node | Approval type | When the graph reaches it | After a rejection |
|---|---|---|---|
| `requirements_review` | `requirements` | Only when a caller passes `from_formal_portal=False`. Both portals pass `True`, so neither reaches this gate | `requirements_gathering` |
| `phenotype_review` | `phenotype_sql` | On every request, before any extraction | `feasibility_validation`. `not_feasible` when the reason says "not feasible", "infeasible", or "cohort too small" |
| `preview_qa_review` | `preview_qa` | Only when the preview check fails | `feasibility_validation` |
| `qa_review` | `delivery` | When the full QA passes | `data_extraction` |

Two more approval types exist outside the graph.

- `scope_change`. `POST /approvals/scope-change` creates the row with an impact analysis. The facade records the decision, and no node consumes it.
- `extraction`. The timeout table, the bridge mapping, and a dashboard filter name it. No code creates an approval of this type.

A reviewer decides in the admin dashboard or through `POST /approvals/{approval_id}/respond`. Both call `LangGraphRequestFacade.process_approval_response`.

- The facade refuses a decision unless the approval is pending and the graph is paused at that approval's gate.
- `FullWorkflow.apply_approval_decision` writes the decision into the paused gate and re-runs the gate's router. The graph then resumes.
- The `reviewer` is free text. The user roles in code are `researcher`, `data_steward`, and `admin`. No role limits who can decide ([#248](https://github.com/jagnyesh/researchflow/issues/248)), and the dashboard has no login.
- `AUTO_APPROVE_FOR_DEV=true` removes all four pauses. The workflow refuses to start with that setting when `ENVIRONMENT=production`.

### Timeouts

`_APPROVAL_TIMEOUT_HOURS` in `app/services/approval_service.py` sets the timeouts in code. No environment variable changes them.

| Approval type | Timeout |
|---|---|
| `requirements`, `phenotype_sql`, `delivery` | 24 hours |
| `extraction` | 12 hours |
| `scope_change` | 48 hours |
| Any other type, including `preview_qa` | 24 hours |

A timeout never fires for a graph gate. `ApprovalBridge.create_approval_request` creates each gate's row without `timeout_at`, and `check_timeouts` skips a row that has none. Under `app/`, only the scope-change route sets `timeout_at`. For those rows, a client must call `POST /approvals/check-timeouts`, and the repo has no scheduler that makes the call.

## Exploratory path

`FeasibilityService.execute_feasibility_check` runs synthesis, validation, and execution. The docstring of `app/services/sql_validator.py` lists the 8 rules of `SQLValidator`. Rule 5 is the PHI (protected health information) boundary. It allows aggregates plus these dimensions: `gender`, `clinical_status`, and columns that end in `_display` or `_code`. `birth_date` can appear only inside an age-bucket expression. The rule denies `postal_code` and any column whose name contains an identifier token, such as `zip`, `phone`, or `_name`.

The validated SQL gets `LIMIT 1000` and runs with a 5-second timeout as `rf_readonly`. `config/rf_readonly_role.sql` grants that role `USAGE` on the `sqlonfhir` schema and `SELECT` on its tables. Any failure returns an error variant that has no cohort number.

## Data layers

ResearchFlow uses a Lambda architecture: a batch layer of precomputed views, a speed layer of recent changes, and a serving layer that merges the two. Each view comes from a SQL-on-FHIR ViewDefinition, a JSON document that maps a FHIR resource type to table columns. The 7 definitions are in `app/sql_on_fhir/view_definitions/`, and [`SQL_ON_FHIR_V2.md`](SQL_ON_FHIR_V2.md) describes the implementation.

| Layer | Class | Behavior |
|---|---|---|
| Batch | `MaterializedViewRunner` | Reads the `sqlonfhir.*` views in HAPI Postgres. `scripts/materialize_views.py` builds them. A refresh is a manual run or a cron job |
| Speed | `SpeedLayerRunner` | Reads recent resources from Redis. `FHIRSubscriptionService` polls HAPI every 30 seconds and writes them with a 24-hour lifetime, or 12 hours for Observations |
| Serving | `HybridRunner` | Routes by `FreshnessAnnotation`. `EXPLORATORY` and `FORMAL_DRAFT` merge batch and speed. On a duplicate id, the merge keeps the speed row. `FORMAL_DRAFT` also records `batch_anchor_ts`. `FORMAL_EXTRACTION` reads batch only |

- [`MATERIALIZED_VIEWS_ARCHITECTURE.md`](MATERIALIZED_VIEWS_ARCHITECTURE.md) reports 5 to 15 ms for a materialized-view query, 10 to 100 times faster than SQL generated for each request.
- The speed layer's design target is data under 1 minute old ([ADR 0004](decisions/0004-sprint-5-5-redis-lambda-speed-layer.md)).
- No code under `app/` starts `FHIRSubscriptionService`. Only `scripts/sprint_6_5_gate.py` constructs it (`grep -rn "FHIRSubscriptionService(" app scripts`).
- `HybridRunner` caches whether each view exists.

### HybridRunner wiring statement

This statement is the one authoritative answer on which code paths use `HybridRunner`. Other mentions defer to it. It was last checked against the code on 2026-11-09.

- **Routes through `HybridRunner`.** The analytics API (`app/api/analytics.py` `/execute`, `/count`, `/query`), in the default `EXPLORATORY` mode.
- **No longer routes through it.** `phenotype_agent` cohort estimation counts the approved phenotype SQL on the batch tables. So the estimate, the `phenotype_review` gate, and the extraction use one cohort definition ([ADR 0033](decisions/0033-phenotype-estimate-counts-approved-sql.md), [#206](https://github.com/jagnyesh/researchflow/issues/206)). `FORMAL_DRAFT` has no production caller.
- **Uses only the freshness helper.** `feasibility_service`, the exploratory portal's service, runs the synthesized and validated SQL directly. It runs as `rf_readonly` through `EXPLORATORY_DB_URL`. It falls back to `HAPI_DB_URL` only when `ENVIRONMENT` is `development` or unset. With any other value, a missing `EXPLORATORY_DB_URL` raises an error ([ADR 0034](decisions/0034-compose-store-urls-match-code.md)). It calls `HybridRunner.get_batch_anchor_ts_for_views` only for the "data as of" line. This path is batch-only by design ([ADR 0028](decisions/0028-sprint-6-7-exploratory-llm-sql-synthesis.md) decision 3).
- **Bypasses it.** `extraction_agent` calls `SQLonFHIRAdapter.execute_sql` directly at three sites (`grep -n "sql_adapter.execute_sql" app/agents/extraction_agent.py`).
- **`FORMAL_EXTRACTION` has no production caller.** `HybridRunner` implements the citability contract, which skips the speed merge and pins the read to `batch_anchor_ts`. Unit tests cover it, and no delivery path invokes it ([ADR 0027](decisions/0027-sprint-6-5-differential-freshness-routing.md)).
- [#71](https://github.com/jagnyesh/researchflow/issues/71) is closed by decision, not deferred. Sprint 6.7 ([#100](https://github.com/jagnyesh/researchflow/issues/100)) deleted the `feasibility_service` half, and extraction stays batch-only under the citability contract. A real freshness requirement for extraction would get a new, narrowly scoped issue.

### Coupling to the HAPI schema

Several components read HAPI FHIR's storage tables directly, not the FHIR REST API. A different FHIR server, or a HAPI release that changes its storage layout, breaks them. The pinned HAPI image in `config/docker-compose.yml` is the compatibility boundary.

- `hfj_resource` and `hfj_res_ver`. Every `sqlonfhir.*` view depends on these tables, through two build paths in `scripts/materialize_views.py`. Views on the sqlonfhir backend read through `app/sql_on_fhir/runner/hapi_db_resource_reader.py`. `app/sql_on_fhir/query_builder/sql_builder.py` compiles the custom-backend views through `PostgresRunner`.
- The same two tables have four more readers: the live queries in `app/clients/hapi_db_client.py`, `app/services/fhir_subscription_service.py`, `scripts/create_materialized_views.py`, and the oracle queries in `tests/fixtures/mv_row_count_oracles.sql`.
- `app/sql_on_fhir/schema/hapi_schema.py` models the full schema, including `hfj_res_link`, `hfj_res_tag`, and every `hfj_spidx_*` table.
- The transpiler in `app/sql_on_fhir/transpiler/column_extractor.py` emits SQL that assumes the `hfj_resource r` alias, as in `r.fhir_id`.

## Security controls

[`HIPAA_POSTURE.md`](HIPAA_POSTURE.md) documents the Sprint 6.1 baseline.

- **Encryption at rest.** `FernetEngine` wraps the Tier 1 columns that can hold PHI: `initial_request`, the inclusion and exclusion criteria, and the phenotype SQL. Three JSON columns are not encrypted: `approvals.approval_data`, `agent_executions.context`, and `agent_executions.result`. They hold copies of that content and the preview's patient rows ([#207](https://github.com/jagnyesh/researchflow/issues/207)).
- **Audit logging.** A default-deny classifier treats every unlisted route as a PHI route. A PHI route returns 401 without a valid token, and 503 when the audit queue cannot record the request.
- **TLS.** With `ENVIRONMENT=production`, the API redirects HTTP with a 308 and sends HSTS for one year with `includeSubDomains`.
- **Input validation.** Request schemas extend `PHIInputModel`, and a 422 response omits the submitted input.
- **Authentication.** A human user gets a JWT from `POST /auth/login`. Routes that change materialized views or ViewDefinitions require the `admin` role. One route is weaker than the rest: `POST /a2a/token` issues a service token to any caller whose `client_id` equals its `client_secret`, a demo check ([#233](https://github.com/jagnyesh/researchflow/issues/233)).

`HIPAA_POSTURE.md` does not yet cover the later security work.

- [ADR 0029](decisions/0029-api-error-path-phi-safe-500s.md): a 500 response and its log line carry a reference id and never the exception message.
- [ADR 0030](decisions/0030-viewdefinition-write-admin-only.md): only an admin can create or delete a ViewDefinition.
- [ADR 0032](decisions/0032-audit-completed-after-body.md): the audit trail records `PHI_ACCESS_COMPLETED` after the response body is sent, with the real status.
- [ADR 0034](decisions/0034-compose-store-urls-match-code.md): the exploratory portal refuses to run without `EXPLORATORY_DB_URL` outside development.
- [PR #357](https://github.com/jagnyesh/researchflow/pull/357): the approval read routes return only approvals for requests that the caller may see.
- [PR #360](https://github.com/jagnyesh/researchflow/pull/360): in a de-identified extract, dates become years, ids become keyed pseudonyms, and unlisted columns are dropped. The extract does not yet meet HIPAA Safe Harbor. Ages over 89 are not top-coded, and free text in `code_text` and `value_string` passes through.

## Known gaps

The README lists the main limits. This table adds the gaps that the README leaves out.

| Gap | Detail | Tracking |
|---|---|---|
| Dashboard authentication | The 3 Streamlit ports (8501, 8502, 8503) skip the API's audit middleware and role checks. A launch from outside the repo root, a `STREAMLIT_SERVER_ADDRESS` variable, or `--server.address 0.0.0.0` skips the `127.0.0.1` pin | Phase 3c, [#39](https://github.com/jagnyesh/researchflow/issues/39) and [#219](https://github.com/jagnyesh/researchflow/issues/219) |
| Researcher PII encryption | `User.email` and `*.researcher_email` are not encrypted | Phase 3b.1 in [`BACKLOG.md`](../BACKLOG.md) |
| Delivery notification | `DeliveryAgent` logs the notification and sends no email | None |
| One institution | No test has run against more than one health system's data | Sprint 11 in [`BACKLOG.md`](../BACKLOG.md) |
