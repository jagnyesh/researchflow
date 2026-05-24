# ResearchFlow Architectural Map — 2026-05-24

Post-Sprint-7.2 + post-Sprint-6.5b refresh of `05-15architecturereview.md`. Generated against current `CONTEXT.md` + `docs/decisions/INDEX.md` + verified against live code on main as of `1cade0a`. Supersedes the 2026-05-15 snapshot which is now historical (kept for chronology — see `05-15architecturereview.md`).

## What changed since 2026-05-15

Five shipments since the previous snapshot, each materially changing one layer:

- **Sprint 6.4** (b64d0d8, 2026-05-15) — DATA LAYER: sqlonfhir engine integration for 3 zero-row MVs (condition_diagnoses, observation_labs, procedure_history); 4 custom-path MVs unchanged
- **Sprint 7.2** (8073a00, 2026-05-17) — ORCHESTRATION: A2A FSM (`app/orchestrator/`, 1,324 LOC) deleted; LangGraph is the only orchestrator
- **Sprint 6.5** (d457fe8, 2026-05-17) — DATA LAYER: HybridRunner gets its first production caller (phenotype_agent) with three-mode `FreshnessAnnotation` routing
- **Sprint 6.5b** (5625d9e, 2026-05-18) — AGENTS: extraction_agent dead-table branches (`FROM observation`, `document_reference`, `medication_request`) removed (-101 LOC); honesty-patch warnings now load-bearing
- **Issue #51 fix** (e7da871, 2026-05-18) — LLM CLIENT: `_parse_age_details` now handles "between X and Y" range syntax; closes gap #6 from the 05-15 snapshot

## Snapshot context

- **Sprint state at capture:** ~21/22 sprints shipped. Phase 2 nearly complete; Phases 3–4 ahead.
- **Active candidates:** Sprint 6.5b expanded (#71, multi-view JOIN HybridRunner wiring), Sprint 6.5c (#82, defensive demographic clause), Sprint 6.6 (custom-path MV health-check), Sprint 7.3 (#65, port 2 deferred A2A tests), Sprint 8.5/8.6 (sparse-traffic + exploratory caching).
- **Known architecture-vs-actual gaps:** 5 (was 6 — gap #6 closed by Issue #51 fix; one new gap added — see #80).

## The map

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ENTRY POINTS (what users + agents touch)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Exploratory Portal  :8501  app/web_ui/research_notebook.py                 │
│     (Text2SQL NL chat — researchers iterate on cohort definitions)          │
│                                                                              │
│  Formal Portal       :8502  app/web_ui/researcher_portal.py                 │
│     (Structured form → 6-agent LangGraph workflow → data delivery)          │
│                                                                              │
│  Admin Dashboard     :8503  app/web_ui/admin_dashboard.py                   │
│     (System monitoring · Cost Telemetry tab · Approvals · Escalations)      │
│                                                                              │
│  FastAPI             :8000  app/main.py                                     │
│     (REST API · MCP routes · A2A auth routes · audit middleware)            │
│                                                                              │
│  ⚠ Three Streamlit ports have ZERO AUTH today (Phase 3c #39 follow-on)      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATION LAYER (singular post-Sprint-7.2)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LangGraph FSM       app/langchain_orchestrator/                            │
│     langgraph_workflow.py — 17 nodes, the ONLY orchestrator                 │
│     request_facade.py — public surface; process_new_request() entry point   │
│     agent_adapter.py — bridges 6 agents into LangGraph nodes                │
│     approval_bridge.py — HITL approvals (4 gates + 1 escalation terminal)   │
│     persistence.py — singleton SqliteSaver checkpointer (Sprint 7)          │
│                                                                              │
│  app/orchestrator/ (custom A2A FSM, 1,324 LOC) — DELETED in Sprint 7.2      │
│  All production callers (researcher_portal, admin_dashboard, main.py,       │
│  approvals API, approval_service) now use LangGraphRequestFacade.           │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  6 PRODUCTION AGENTS (all subclass BaseAgent, all @traceable)               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Requirements    Sonnet — extract_requirements + extract_medical_concepts   │
│                  ↑ the ONLY agent that invokes LLM children today           │
│                  (Haiku for concept extraction; Sonnet for batch dialog)    │
│                                                                              │
│  Phenotype       Generates SQL via SQLGenerator →                           │
│                  ➡ HybridRunner.execute(mode=FORMAL_DRAFT) ✓                │
│                  (Sprint 6.5 wired; FIRST production HybridRunner caller)   │
│                                                                              │
│  Calendar        Time-window resolution (no LLM)                            │
│                                                                              │
│  Extraction      Executes phenotype SQL via SQLonFHIRAdapter (bypasses     │
│                  HybridRunner ⚠ — Sprint 6.5b expanded #71 for multi-view  │
│                  JOIN API extension). Sprint 6.5b removed dead-table       │
│                  branches; only demographics dispatch is live today.        │
│                                                                              │
│  QA              Validates extraction results (no LLM)                      │
│                                                                              │
│  Delivery        Builds delivery package; surfaces extraction_warnings      │
│                  from data_package under "⚠ EXTRACTION WARNINGS:" header   │
│                  in delivery README (Sprint 6.5 honesty patch)              │
│                                                                              │
│  8 @traceable sites (6 agents + query_interpreter + feasibility_service)   │
│  carry `portal:formal` or `portal:exploratory` tags. Tag inheritance to     │
│  LLM leaves drives Cost Telemetry aggregation.                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  LLM CLIENT LAYER (post-Sprint-8 series, post-Issue-#51)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  app/utils/llm_client.py                                                    │
│     LLMClient + MultiLLMClient                                              │
│     _ANTHROPIC_CACHE_THRESHOLDS = {sonnet: 1024, haiku: 4096}              │
│     _REQUIREMENTS_SYSTEM_PROMPT (~3000 tokens, Sonnet, cached 94.88%)       │
│     _MEDICAL_CONCEPTS_SYSTEM_PROMPT (~5185 tokens, Haiku, cached 100%)      │
│                                                                              │
│  Wire shape (post-Sprint-8.2, mandatory for cache_control transmission):    │
│     SystemMessage(content=[{"type":"text","text":...,"cache_control":...}]) │
│     ← langchain-anthropic 1.0.1 silently drops cache_control if content is │
│       a plain string instead of a content-block array                      │
│                                                                              │
│  app/utils/sql_generator.py                                                 │
│     _parse_age_details now handles 3 shapes (Issue #51 fix, May 18):        │
│       ('>',  N)      for greater-than ('> 18', 'over 65', 'above 50')       │
│       ('<',  N)      for less-than    ('< 65', 'under 18', 'below 21')      │
│       ('BETWEEN', (lo, hi))  for ranges ('between 40 and 65', 'aged 20-29') │
│     _build_demographic_clause emits inclusive BETWEEN SQL for the range     │
│     case; this closes gap #6 from the 05-15 snapshot (was: range syntax    │
│     silently produced empty SQL).                                           │
│                                                                              │
│  app/services/query_interpreter.py                                          │
│     Used by Exploratory Portal                                              │
│     ⚠ cache_hit_rate = 0.0000% (below Anthropic threshold — Sprint 8.6)    │
│                                                                              │
│  app/services/feasibility_service.py                                        │
│     Cohort-count probes — builds SQL via JoinQueryBuilder, executes via     │
│     db_client (bypasses HybridRunner ⚠ — Sprint 6.5b expanded #71)         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  DATA LAYER (Lambda Architecture — documented vs actual, post-Sprint-6.5)   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  DOCUMENTED + ACTUAL READ PATH (phenotype_agent, post-Sprint-6.5):          │
│                                                                              │
│      phenotype_agent → HybridRunner.execute(mode=FreshnessAnnotation)       │
│                            ├─ MaterializedViewRunner  (batch, nightly)      │
│                            ├─ SpeedLayerRunner  (Redis, 24hr TTL)           │
│                            └─ merge + dedup (mode-conditional)              │
│                                                                              │
│      Mode semantics (Sprint 6.5):                                           │
│        EXPLORATORY     → batch + speed merge (default for Text2SQL)         │
│        FORMAL_DRAFT    → batch + speed merge + batch_anchor_ts surfaced     │
│                          (pre-approval cohort estimation)                   │
│        FORMAL_EXTRACTION → batch-only, NO speed merge                       │
│                          (citability contract: same SQL × same anchor =     │
│                           bit-identical row-set, audit-defensible)          │
│                                                                              │
│  STILL-BYPASSED READ PATHS (Sprint 6.5b expanded #71):                      │
│                                                                              │
│      extraction_agent._execute_phenotype_query → SQLonFHIRAdapter (direct) │
│      feasibility_service.execute_feasibility_check → db_client (direct)    │
│                                                                              │
│  Both bypass because their SQL is multi-view JOIN shape that HybridRunner's│
│  current single-view-def API doesn't accept. #71 will extend HybridRunner   │
│  with `execute_sql_with_view_hints(sql, view_names, mode)` and wire both   │
│  callers through it. Currently filed as candidate (driver pending).         │
│                                                                              │
│  BATCH WRITE PATH (Sprint 6.4 hybrid: 4 custom + 3 sqlonfhir):              │
│                                                                              │
│      scripts/materialize_views.py                                           │
│         → backend_dispatcher.select_backend(view_def)                       │
│              ├─ custom-path (4 view_defs):                                  │
│              │     postgres_runner.py + fhirpath_transpiler                 │
│              │     (patient_simple, patient_demographics,                   │
│              │      condition_simple, medication_requests)                  │
│              └─ sqlonfhir-path (3 view_defs):                               │
│                    hapi_db_resource_reader + sqlonfhir.evaluate()          │
│                    (condition_diagnoses, observation_labs, procedure_      │
│                     history — Sprint 6.4 swap point, runner_hint flag)     │
│         → mv_health_check.run_post_write_check()                            │
│              same-run oracle, 5% threshold, N=3 consecutive-warn alarm,    │
│              JSONL log at logs/mv_health.jsonl                             │
│         → write sqlonfhir.mv_refresh_metadata row                           │
│              (citation anchor source for FORMAL_EXTRACTION batch_anchor_ts) │
│                                                                              │
│  RUNNER STACK (app/sql_on_fhir/runner/):                                    │
│      hybrid_runner.py — serving layer + FreshnessAnnotation routing         │
│      freshness.py — the enum (Sprint 6.5)                                  │
│      materialized_view_runner.py — batch reads from sqlonfhir.<view>       │
│      speed_layer_runner.py — Redis reads, overlay merge                     │
│      postgres_runner.py — direct HAPI reads + custom-path MV writes        │
│      backend_dispatcher.py — runner_hint routing (Sprint 6.4)              │
│      mv_health_check.py — post-write oracle (Sprint 6.4)                   │
│      hapi_db_resource_reader.py — HAPI internal schema → sqlonfhir input   │
│      in_memory_runner.py — test oracle from Sprint 6.2 transpiler harness  │
│                                                                              │
│  TRANSPILER (app/sql_on_fhir/transpiler/):                                  │
│      fhirpath_transpiler.py — 48/48 harness tests; covers 4 custom-path    │
│      MVs. Sprint 6.4 introduced sqlonfhir as a per-view-def alternative;    │
│      the transpiler stays in use for the 4 view_defs that don't declare   │
│      `runner_hint: sqlonfhir`.                                             │
│                                                                              │
│  NEW TABLES (Sprint 6.5):                                                   │
│      sqlonfhir.hybrid_runner_metrics — per-execute row with mode,          │
│         view_names, batch_anchor_ts, speed_layer_hit, latency_ms,          │
│         caller, trace_id                                                    │
│      sqlonfhir.mv_refresh_metadata — view_name + refreshed_at + row_count │
│         + view_definition_hash (the citation-anchor source of truth)        │
│                                                                              │
│  DATABASE TOPOLOGY (unchanged):                                             │
│      :5432 host Postgres — Synthea CSV (NOT runtime, dev/exploration)       │
│      :5433 Docker HAPI Postgres — hfj_resource + sqlonfhir.<view>           │
│         Current MV counts: 375 patients, 14,841 conditions,                │
│         157,689 observations, 66,448 procedures                            │
│      :6379/:6380 Redis — audit queue + speed layer cache                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  OBSERVABILITY (Sprint 8 series stable; cost telemetry trustworthy)         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LangSmith                                                                  │
│     @traceable decorators on 8 sites (6 agents + query_interpreter +        │
│     feasibility_service) carry `portal:formal` or `portal:exploratory`      │
│     tags. Tag inheritance propagates to LLM leaves.                         │
│                                                                              │
│  app/services/cost_telemetry_service.py                                     │
│     Read-side aggregator. Source of truth for LLM cost (post-Sprint-8.4    │
│     aggregator fix). Median formal-portal cost: $0.008 per request.         │
│     FORMAL_BAND_CEILING_USD     = 0.010080  (Sprint 8.3 derivation)         │
│     EXPLORATORY_BAND_CEILING_USD = 0.004602  (Sprint 8.3 derivation)        │
│     Both = measured_median × 1.3 (regression alarm vs current baseline)     │
│                                                                              │
│  Admin Dashboard "💰 Cost Telemetry" tab                                    │
│     Renders both portals' gate-status (🟢/🔴) against the ceilings above   │
│                                                                              │
│  scripts/drive_qa_traffic.py                                                │
│     Synthetic-traffic harness (30 requests in 6-7 min, within cache TTL)    │
│     Used by every Sprint 8 verification + ceiling re-derivation             │
│                                                                              │
│  Sprint 6.5 added per-execute metric writes:                                │
│     sqlonfhir.hybrid_runner_metrics — Postgres row + LangSmith RunTree     │
│     metadata. Same row-shape mirrored in both sinks (HybridRunnerMetric     │
│     dataclass is the single source of truth).                              │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  SECURITY BASELINE (Sprint 6.1 shipped 2026-05-08; unchanged since 05-15)   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  app/security/                                                              │
│     audit middleware → Redis queue → audit_drain → Postgres audit_logs      │
│     fail-closed default-deny on PHI routes; allowlist for /health, /docs    │
│     TLS enforcement gated by ENVIRONMENT=production                         │
│     encryption-at-rest on Tier 1 PHI columns (FernetEngine)                 │
│                                                                              │
│  app/schemas/                                                               │
│     PHIInputModel base + typed primitives (ShortText, IRBNumber, etc.)      │
│     PHI-safe RequestValidationError handler (strips input/url/ctx)          │
│                                                                              │
│  app/api/users.py + app/a2a/auth.py                                         │
│     Split human/agent auth: Depends(get_current_user) vs                    │
│     verify_service_token() for /a2a, /mcp routes                            │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  KNOWN ARCHITECTURE-VS-DOCUMENTATION GAPS                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. HybridRunner partial wiring.                                            │
│     Sprint 6.5 wired phenotype_agent (single-view-def path). Multi-view    │
│     JOIN callers (feasibility_service, extraction_agent) still bypass via  │
│     SQLonFHIRAdapter. Needs `execute_sql_with_view_hints` API extension.   │
│     → Sprint 6.5b expanded (#71).                                           │
│                                                                              │
│  2. Streamlit dashboards (3 ports) have zero authentication.                │
│     → Phase 3c (#39) — must land before/with Phase 3b.1 PII encryption.    │
│                                                                              │
│  3. QueryInterpreter (Exploratory) has cache_hit_rate=0%.                   │
│     → Sprint 8.6 candidate — bulk prompt + ensure langchain content-block   │
│       form applied at the call site (mirrors Sprint 8.2 formal fix).        │
│                                                                              │
│  4. Cost Telemetry ceilings are bursty-traffic calibrated.                  │
│     → Sprint 8.5 candidate — sparse-traffic measurement when real prod      │
│       traffic produces gaps > 5min cache TTL.                               │
│                                                                              │
│  5. HAPI FHIR Docker healthcheck is broken (distroless image, no /bin/sh).  │
│     → Cosmetic — serves 200 fine; healthcheck shows "unhealthy" anyway.     │
│                                                                              │
│  6. sql_generator.py:507 raw `FROM observation o` in _build_lab_value_     │
│     criterion. Same dead-code class as Sprint 6.5b cleanup. Phenotypes     │
│     with lab-value criteria would silently produce 0-patient cohorts.       │
│     Currently masked because no test traffic hits this code path.           │
│     → Sprint 6.5b followup (#80).                                           │
│                                                                              │
│  7. _build_demographic_clause age-first early-return is structurally        │
│     fragile (compound term="age gender" would drop gender). Sprint 6.5b's  │
│     25-input stress test confirmed it does NOT fire in production today    │
│     because the LLM emits gender + age as separate concepts per the prompt.│
│     → Sprint 6.5c candidate (#82) — defensive hardening only.              │
│                                                                              │
│  (Closed since 2026-05-15: gap #6 "phenotype agent SQL drops gender + age" │
│  was Issue #51 — fixed 2026-05-18 by `_parse_age_details` range support.)  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  FORWARD MAP — where the next sprints live                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Sprint 6.5b   DATA LAYER multi-view JOIN HybridRunner wiring (#71)         │
│                — closes gap #1 fully; needs API extension first             │
│  Sprint 6.5c   LLM CLIENT defensive demographic clause fall-through (#82)   │
│                — closes gap #7; latent, not firing today                    │
│  Sprint 6.6    DATA LAYER custom-path MV health-check oracles               │
│                — adds explicit oracles for the 4 transpiler-path MVs        │
│  Sprint 7.3    AGENTS port 2 deferred A2A behavioral tests (#65)            │
│                — `test_agent_handoffs.py` + `test_admin_dashboard_updates.py` │
│  Sprint 8.5    OBSERVABILITY sparse-traffic ceiling calibration             │
│                — closes gap #4                                              │
│  Sprint 8.6    LLM CLIENT exploratory portal caching                        │
│                — closes gap #3                                              │
│  Sprint 9      AGENTS temporal reasoning engine (HbA1c >7 within 6mo)       │
│  Sprint 10     AGENTS complex cohort logic (nested AND/OR/NOT, exclusions)  │
│  Sprint 11     ENTRY POINTS multi-tenant architecture                       │
│  Phase 3c      ENTRY POINTS streamlit auth — closes gap #2                  │
│  Phase 3b.1    SECURITY researcher-PII encryption (User.email, etc.)        │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Load-bearing observation

**The Sprint 6.5 closure of gap #1 (partial) is the through-line of the May 15-24 window.** HybridRunner went from "exercised by tests + batch refresh, no production caller" to "phenotype_agent's serving layer with three-mode freshness routing." The DATA LAYER is now genuinely-Lambda for one critical read path.

The remaining HybridRunner-bypass surface — feasibility_service + extraction_agent — is a different shape (multi-view JOIN) and needs an API extension (#71). Closing the rest of gap #1 requires designing what "merge for a JOIN count" means semantically, not just wiring.

Sprint 6.5b's narrower cleanup (extraction_agent dead-table branches) surfaced the LLM-prompt-followed-instruction insight: the prompt asks for separate gender + age concepts, and the LLM complies. The latent age-first early-return (#82) doesn't fire because the production input never triggers the precondition. Both #71 and #82 stay candidates until a driving requirement surfaces.

## Snapshot caveat

This map is frozen at the timestamp in the header (2026-05-24). Domain glossary terms (`Formal Portal`, `Exploratory Portal`, `HybridRunner`, `FreshnessAnnotation`, `batch_anchor_ts`) are stable; specific cost numbers, cache_hit_rates, and Sprint statuses drift quickly. For current values, consult `CONTEXT.md` (living state) and `docs/decisions/INDEX.md` (append-only ADR log). For active follow-ups, consult `BACKLOG.md`. For historical chronology, the 2026-05-15 snapshot remains at `05-15architecturereview.md`.
