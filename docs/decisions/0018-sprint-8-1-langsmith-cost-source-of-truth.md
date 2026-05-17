---
sprint: 8.1
date: 2026-05-12
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 8.1 — LangSmith is source-of-truth for LLM cost; explicit portal tags promote domain language into trace data

Two coupled decisions for the cost-verification sprint. **(1) Read cost/latency telemetry directly from LangSmith.** The Sprint 8 archive doc deferred a `QueryTelemetry` Postgres table as "Optimization 10." Sprint 8.1 re-grilled the question and rejected the table. `@traceable` decorators already ship token counts (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`) for all 6 production agents and `MultiLLMClient.complete` — the data exists upstream. Building a parallel write path means: (a) duplicate code on the LLM call hot path; (b) two sources of truth that can silently drift; (c) ownership of a schema we'd otherwise let LangSmith own. Trade accepted: dashboard reads depend on LangSmith API quota and uptime. We already depend on LangSmith for tracing — making it explicit for reads doesn't expand the blast radius. Offline-dev dashboards display "no recent data" instead of stale local rows, which is the honest UX. Hybrid (`prompt_cost_daily` aggregation table populated by a periodic LangSmith pull) was rejected for this sprint: cron-based aggregation is the right shape if and only if (a) the dashboard becomes hot enough that LangSmith API rate-limits bite, or (b) we want to outlive the LangSmith subscription. Neither is true today; defer to a future sprint with a real trigger.

**(2) Differentiate portal traffic via explicit `portal:formal` / `portal:exploratory` tags on `@traceable` decorators.** The codebase already tags by agent name (`requirements-agent`, `phenotype-agent`, etc. for formal; `feasibility-service`, `hybrid-runner` for exploratory) but has no portal-level tag. Three options considered: (a) tag-based inference at query time (fragile rule "if any tag matches `*-agent` then formal"); (b) separate LangSmith projects per portal (clean separation but two-project ops overhead); (c) add explicit `portal:formal` / `portal:exploratory` tags to the 8 `@traceable` decorators (6 formal agents + `query_interpreter` + `feasibility_service`). **Chose (c).** ~8 single-line additions, promotes the documented "Formal Portal" / "Exploratory Portal" domain vocabulary into trace data, makes `cost_telemetry_service.py` queries trivially `has(tags, "portal:formal")` rather than encoding an inference rule. Future-me reads the tag and knows immediately what portal a run belongs to.

**Aggregation rules** (independent of the source-of-truth choice): formal portal groups runs by LangSmith `thread_id` (LangGraph checkpointer sets it per workflow invocation; one thread = one user submission). Exploratory portal aggregates per root trace (one root = one query; QueryInterpreter is the typical entry point). `cost_telemetry_service.get_formal_portal_cost_p50(n=30)` computes sum-tokens-per-thread × per-model-price, sorted by start time desc, median of last 30 threads.

**Sprint 8.1 gate (pre-committed):** median cost-per-request ≤ 1.3× projected, rolling 30 requests, both portals clear independently. Failure mode: sprint closes either way; if red, BACKLOG gets a Sprint 8.2 entry for the gap-close work.
