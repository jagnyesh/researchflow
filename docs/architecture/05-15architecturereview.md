# ResearchFlow Architectural Map — 2026-05-15

Post-Sprint-8-series zoom-out. Generated from a /zoom-out skill invocation against CONTEXT.md + DECISIONS.md + session memory immediately after the Sprint 8 series closed (Sprint 8.3 merged 2026-05-14 as `a8fa059`). Uses the project's domain glossary throughout.

## Snapshot context

- **Sprint state at capture:** Sprint 6.1/6.2 SHIPPED, Sprint 8 series CLOSED (8.1/8.2/8.4/8.3 all merged 2026-05-12 through 2026-05-14), Sprint 6.3 spike VERDICT GO sqlonfhir. ~16/22 sprints overall.
- **Active follow-ups:** Sprint 6.4 (sqlonfhir integration), Sprint 8.5/8.6 candidates filed by Sprint 8.3.
- **Architecture-vs-documentation gaps:** 6 known, enumerated below.

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
│     (REST API · MCP routes · A2A routes · auth · audit middleware)          │
│                                                                              │
│  ⚠ Three Streamlit ports have ZERO AUTH today (Phase 3c #39 follow-on)      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATION LAYER (two parallel implementations)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Custom A2A FSM      app/orchestrator/                                      │
│     workflow_engine.py · orchestrator.py — 15-state FSM, production         │
│                                                                              │
│  LangGraph FSM       app/langchain_orchestrator/                            │
│     langgraph_workflow.py — 17 nodes, behind USE_LANGGRAPH_WORKFLOW flag    │
│     agent_adapter.py — bridges 6 agents into LangGraph nodes                │
│     approval_bridge.py — HITL approvals (requirements/phenotype/extraction) │
│                                                                              │
│  Both call into the same 6 BaseAgent subclasses below.                      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  6 PRODUCTION AGENTS (all subclass BaseAgent, all @traceable)               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Requirements    Sonnet — extract_requirements + extract_medical_concepts   │
│                  ↑ the ONLY agent that invokes LLM children today           │
│                                                                              │
│  Phenotype       Generates SQL via SQLGenerator → executes via              │
│                  SQLonFHIRAdapter (bypasses HybridRunner ⚠)                 │
│                                                                              │
│  Calendar        Time-window resolution (no LLM)                            │
│                                                                              │
│  Extraction      Executes phenotype SQL via SQLonFHIRAdapter (no LLM)       │
│                                                                              │
│  QA              Validates extraction results (no LLM)                      │
│                                                                              │
│  Delivery        Builds delivery package + notification (no LLM)            │
│                                                                              │
│  All 8 @traceable sites carry `portal:formal` tag (6 agents +               │
│  query_interpreter + feasibility_service). Tag inheritance to LLM leaves    │
│  drives Cost Telemetry aggregation.                                         │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  LLM CLIENT LAYER (the Sprint 8 series surface)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  app/utils/llm_client.py                                                    │
│     LLMClient + MultiLLMClient                                              │
│     _ANTHROPIC_CACHE_THRESHOLDS = {sonnet: 1024, haiku: 4096}              │
│     _REQUIREMENTS_SYSTEM_PROMPT (~3000 tokens, Sonnet, cached 94.88%)       │
│     _MEDICAL_CONCEPTS_SYSTEM_PROMPT (~5185 tokens, Haiku, cached 100%)      │
│                                                                              │
│  Wire shape post-Sprint-8.2:                                                │
│     SystemMessage(content=[{"type":"text","text":...,"cache_control":...}]) │
│     ← langchain-anthropic 1.0.1 ONLY transmits cache_control in this form   │
│                                                                              │
│  app/services/query_interpreter.py                                          │
│     Used by Exploratory Portal                                              │
│     ⚠ cache_hit_rate = 0.0000% (below Anthropic threshold — Sprint 8.6)    │
│                                                                              │
│  app/services/feasibility_service.py                                        │
│     Cohort-count probes — builds SQL via JoinQueryBuilder, executes via     │
│     db_client (bypasses HybridRunner ⚠)                                     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  DATA LAYER (Lambda Architecture — documented vs actual)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  DOCUMENTED READ PATH:                                                      │
│                                                                              │
│      caller → HybridRunner.execute()                                        │
│                  ├─ MaterializedViewRunner  (batch, nightly refresh)        │
│                  ├─ SpeedLayerRunner        (Redis, 24hr TTL)               │
│                  └─ merge + dedup                                           │
│                                                                              │
│  ACTUAL PRODUCTION READ PATH:                                               │
│                                                                              │
│      phenotype_agent  → SQLGenerator → SQLonFHIRAdapter ─┐                  │
│      extraction_agent → (same SQL)   → SQLonFHIRAdapter ─┼─→ Postgres :5433│
│      feasibility_service → JoinQueryBuilder → db_client ─┘                  │
│                                                                              │
│  HybridRunner is exercised by tests + batch refresh path. Not on any        │
│  production read hot-path. Filed as Sprint 6.5+ candidate to wire agents    │
│  through it (would unlock speed-layer merge for online reads).              │
│                                                                              │
│  BATCH WRITE PATH (Sprint 6.4 swap point):                                  │
│                                                                              │
│      scripts/materialize_views.py → postgres_runner.py (write mode)         │
│      Currently uses custom FHIRPath transpiler; Sprint 6.4 swaps to         │
│      sqlonfhir (SAS Healthcare Apache 2.0 lib, GO verdict 2026-05-14)       │
│                                                                              │
│  TRANSPILER:                                                                │
│      app/sql_on_fhir/transpiler/fhirpath_transpiler.py                      │
│      48/48 harness tests, 7/7 view defs materialize (Sprint 6.2)            │
│      Sprint 6.4 will deprecate this in favor of sqlonfhir                   │
│                                                                              │
│  DATABASE TOPOLOGY:                                                         │
│      :5432 host Postgres — Synthea CSV (NOT runtime, dev/exploration)       │
│      :5433 Docker HAPI Postgres — hfj_resource + sqlonfhir.<view>           │
│      :6379/:6380 Redis — audit queue + speed layer                          │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  OBSERVABILITY (Sprint 8.1/8.2/8.3/8.4 surface)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LangSmith                                                                  │
│     @traceable decorators on 8 sites (6 agents + query_interpreter +        │
│     feasibility_service) carry `portal:formal` or `portal:exploratory`      │
│     tags. Tag inheritance propagates to LLM leaves.                         │
│                                                                              │
│  app/services/cost_telemetry_service.py                                     │
│     Read-side aggregator. Source of truth for LLM cost.                     │
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
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  SECURITY BASELINE (Sprint 6.1 shipped 2026-05-08)                          │
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
│  1. HybridRunner is the documented Lambda read path; agents bypass it.      │
│     → Sprint 6.5+ candidate to close this gap (after Sprint 6.4 lands).     │
│                                                                              │
│  2. Streamlit dashboards (3 ports) have zero authentication.                │
│     → Phase 3c (#39) — must land before/with Phase 3b.1 PII encryption.     │
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
│  6. Phenotype agent SQL drops gender + age predicates in some cases.        │
│     → Logged in BACKLOG observability follow-ons; needs dedicated issue.    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  FORWARD MAP — where the next sprints live                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Sprint 6.4    DATA LAYER write-path swap (sqlonfhir replaces transpiler)   │
│  Sprint 6.5    DATA LAYER agents-through-HybridRunner (closes gap #1)       │
│  Sprint 8.5    OBSERVABILITY sparse-traffic ceiling calibration             │
│  Sprint 8.6    LLM CLIENT exploratory portal caching (closes gap #3)        │
│  Sprint 9      AGENTS temporal reasoning engine (HbA1c >7 within 6mo)       │
│  Sprint 10     AGENTS complex cohort logic (nested AND/OR/NOT, exclusions)  │
│  Sprint 11     ENTRY POINTS multi-tenant architecture                       │
│  Phase 3c      ENTRY POINTS streamlit auth (closes gap #2)                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Load-bearing observation

**Most of the Sprint 8 series surface lives in the LLM CLIENT + OBSERVABILITY rows.** Sprint 6.4 moves to a different row entirely (data layer write-path). The architectural-vs-documented gap (#1, HybridRunner-bypass) is the through-line that future Sprint 6.5 closes — and it's been quietly accumulating since Sprint 6.2 shipped the runner stack.

## Snapshot caveat

This map is frozen at the timestamp in the header. Domain glossary terms (`Formal Portal`, `Exploratory Portal`, `HybridRunner`, etc.) are stable; specific cost numbers, cache_hit_rates, and Sprint statuses drift quickly. For current values, consult `CONTEXT.md` (living state) and `DECISIONS.md` (append-only ADR log). For active follow-ups, consult `BACKLOG.md`.
