# Project history

ResearchFlow started as six agents that passed work to each other. It is now a fixed workflow in which one step calls an LLM. This doc explains that change, the four engineering arcs behind the current code, and what the Sprint 8 series taught. The [ADR index](decisions/INDEX.md) is the primary record.

## Why the docs say "workflow steps" and not "agents"

The first design routed tasks between six agents through a custom agent-to-agent (A2A) state machine. Three changes removed the basis for that description.

- Sprint 7.2 deleted the A2A orchestrator. A LangGraph graph with fixed edges now decides every transition ([ADR 0024](decisions/0024-sprint-7-2-a2a-fsm-closeout.md)).
- Sprint 8.2 measured 2 LLM calls for each formal request, where the cost plan had assumed 6. Both calls are in the requirements step.
- [PR #359](https://github.com/jagnyesh/researchflow/pull/359) removed `CalendarAgent` and `MultiLLMClient` ([#344](https://github.com/jagnyesh/researchflow/issues/344)), so no step does scheduling.

The classes keep the name `Agent` because they subclass `BaseAgent`. In prose, "workflow step" describes them better. The decisions sit in the graph and with the reviewers, not in the steps.

## Foundation: Sprints 1 to 5

Sprints 1 to 3 prototyped the requirements step in LangChain, a small test graph in `simple_workflow.py`, and the full workflow, which had 15 states then. Sprint 4 benchmarked LangGraph against the custom A2A state machine, and both passed 71 of 71 tests. The decision was to keep the custom orchestrator in production and build the migration behind a feature flag ([ADR 0001](decisions/0001-sprint-4-keep-custom-fsm-langgraph-parallel-target.md)). Sprint 5 added LangSmith tracing with `@traceable` ([ADR 0003](decisions/0003-sprint-5-langsmith-observability.md)). Every later measurement depends on those traces.

## Four engineering arcs

### A Lambda architecture for clinical data

This arc ran through Sprints 4.5, 5.5, 6.2, 6.3, 6.4, and 6.5.

- Sprint 4.5 built the batch layer of materialized views, for a 10 to 100 times speedup ([ADR 0002](decisions/0002-sprint-4-5-lambda-batch-materialized-views.md)).
- Sprint 5.5 added the Redis speed layer ([ADR 0004](decisions/0004-sprint-5-5-redis-lambda-speed-layer.md)).
- Sprint 6.2 (2026-05-08) fixed 15 cataloged transpiler bugs with test-driven development ([ADR 0014](decisions/0014-sprint-6-2-phase-1-5-lambda-finish-proceed-gate.md)).
- Sprint 6.3 (2026-05-14) ran an engine spike that chose Pathling and then revised the verdict to sqlonfhir on the same day. ADRs 0019 and 0020 record both verdicts.
- Sprint 6.4 (2026-05-15) moved 3 views that returned zero rows to the sqlonfhir engine. Their row counts then matched the HAPI oracle ([ADR 0026](decisions/0026-sprint-6-4-sqlonfhir-integration.md)).
- Sprint 6.5 (2026-05-17) added three-mode freshness routing: `EXPLORATORY`, `FORMAL_DRAFT`, and `FORMAL_EXTRACTION` ([ADR 0027](decisions/0027-sprint-6-5-differential-freshness-routing.md)).

The arc built more than the product uses today. Only the analytics API routes through `HybridRunner`, as the [wiring statement](ARCHITECTURE.md#hybridrunner-wiring-statement) records.

### From the custom orchestrator to LangGraph

This arc ran through Sprints 1, 2, 3, 4, 7, and 7.2. Sprint 7 finished the LangGraph integration with a singleton checkpointer and `@traceable` on all 6 agents of that time ([ADR 0006](decisions/0006-sprint-7-langgraph-migration-finalized.md)). Sprint 7.2 (2026-05-17) then deleted `app/orchestrator/`, 1,324 lines, behind a parity harness. The sprint removed about 3,200 lines net.

The parity gate first reported "FAILED": 90 of 150 comparisons were blocking. A diagnostic showed what the harness had compared: LangGraph runs that had completed, and A2A runs that were paused at their first gate. [ADR 0000](decisions/0000-meta-recurring-workflow-pattern.md) records the pattern. Check what a verdict measured before you act on it.

### LLM cost telemetry: a projection falsified, then repaired

This arc ran through Sprints 8, 8.1, 8.2, 8.4, and 8.3.

- Sprint 8 projected a 73% cost reduction.
- Sprint 8.1 measured a 0.0% cache hit rate on both portals. The formal median was $0.009026, about 3 times the projected ceiling.
- Sprint 8.2 found three concurrent failures. One was a `langchain-anthropic` bug that had dropped `cache_control` for six months.
- Sprint 8.4 fixed a cost aggregator that over-counted by 2.95 times.
- Sprint 8.3 re-derived the ceilings from measured medians.

The original hypothesis was that provider routing would cut cost. The measurements falsified it. Cost depends on caching and on how few steps call an LLM, not on the provider. ADRs 0018 to 0025 record the series.

### Security baseline

Sprint 6 replaced 30 SQL-injection findings with parameterized SQL through SQLAlchemy `text()` ([ADR 0005](decisions/0005-sprint-6-parameterized-sql.md)). Sprint 6.1 shipped the HIPAA baseline on 2026-05-08. [Architecture](ARCHITECTURE.md#security-controls) lists its controls. Phases 2.2 and 2.3 alone added 74 audit tests and 163 schema tests ([`HIPAA_POSTURE.md`](HIPAA_POSTURE.md)).

## What the Sprint 8 series taught

The Sprint 8 series ran from 2026-05-12 to 2026-05-14 and shipped no feature. It did more for the project's engineering rigor than any other sprint.

1. **Test at the wire, not at the wrapper.** `langchain-anthropic 1.0.1` dropped `cache_control` when a `SystemMessage` held a plain string. The tests asserted on the LangChain input, so they passed while the wrong payload went to Anthropic. [PR #45](https://github.com/jagnyesh/researchflow/pull/45) fixed the bug and added `tests/test_prompt_optimization.py::TestPromptCachingWireLevel`. That test patches `AsyncMessages.create` and asserts that `cache_control` is in the outbound payload ([ADR 0021](decisions/0021-sprint-8-2-prompt-caching-bug.md)).
2. **Check the aggregator by hand.** LangSmith's `Run.input_tokens` already includes `cache_read_input_tokens`, and `CostTelemetryService` billed the cache-read tokens a second time. A manual walk of the trace tree gave $0.007754. The aggregator reported $0.022865. Sprint 8.4 shipped a one-line fix and a fixture test ([ADR 0023](decisions/0023-sprint-8-4-aggregator-cache-read-double-charge.md)).
3. **A pre-commitment defends against bias, not against information.** Sprint 6.3 applied four pre-committed criteria and reached "GO Pathling". A re-examination showed that a view-definition bug had broken the row-count gate's premise for every engine. With the definition patched, 3 of 3 views passed, and the verdict became "GO sqlonfhir" the same day ([ADR 0020](decisions/0020-sprint-6-3-verdict-revision-go-sqlonfhir.md)).

## Shipped log

The newest entry is first. The arcs above cover the sprints before Sprint 6.5b.

- **2026-11-09.** Formal cohorts with an age criterion count living patients only ([ADR 0035](decisions/0035-formal-age-cohorts-living-only.md)). [PR #408](https://github.com/jagnyesh/researchflow/pull/408) removed the dead `/auth/token` route.
- **2026-11-07.** [PR #359](https://github.com/jagnyesh/researchflow/pull/359) removed `CalendarAgent`.
- **2026-11-04.** The phenotype estimate counts the approved SQL ([ADR 0033](decisions/0033-phenotype-estimate-counts-approved-sql.md)).
- **2026-10-21 to 2026-11-07.** The security work after Sprint 6.1, which [Architecture](ARCHITECTURE.md#security-controls) lists with its ADRs and PRs.
- **2026-07-12, Sprint 6.7.** The LLM writes the exploratory SQL behind `SQLValidator`. The sprint retired `JoinQueryBuilder` and `QueryInterpreter`, 2,643 lines, closed [#76](https://github.com/jagnyesh/researchflow/issues/76), and raised the exploratory cache hit rate from 0% to 95%. That result resolved the Sprint 8.6 candidate ([ADR 0028](decisions/0028-sprint-6-7-exploratory-llm-sql-synthesis.md)).
- **2026-05-18.** `_parse_age_details` handles the "between X and Y" age format and emits a SQL `BETWEEN` predicate ([PR #83](https://github.com/jagnyesh/researchflow/pull/83), [#51](https://github.com/jagnyesh/researchflow/issues/51)).
- **2026-05-18, Sprint 6.5b.** Dead-code cleanup in `extraction_agent.py` ([PR #81](https://github.com/jagnyesh/researchflow/pull/81), [#79](https://github.com/jagnyesh/researchflow/issues/79)).

Four follow-up issues from those sprints are also closed: [#82](https://github.com/jagnyesh/researchflow/issues/82), [#65](https://github.com/jagnyesh/researchflow/issues/65), [#80](https://github.com/jagnyesh/researchflow/issues/80), and [#53](https://github.com/jagnyesh/researchflow/issues/53).

## What comes next

Phase 2 is nearly complete, and Phases 3 and 4 are ahead. [`BACKLOG.md`](../BACKLOG.md) has the plan for Sprints 9 to 12 and its decision gates. Two candidates are open from the work above. Sprint 6.6 adds health-check oracles for the custom-path materialized views. Sprint 8.5 measures the median cost under sparse traffic.

## Built with

[FastAPI](https://fastapi.tiangolo.com/), the [Anthropic Claude API](https://www.anthropic.com/), [LangGraph](https://github.com/langchain-ai/langgraph), [LangSmith](https://www.langchain.com/langsmith), [Streamlit](https://streamlit.io/), and the SQL-on-FHIR v2 specification from [HL7 FHIR](https://hl7.org/fhir/). I developed the project with Claude Code and a habit of questioning each plan before implementation. [ADR 0000](decisions/0000-meta-recurring-workflow-pattern.md) documents the patterns that emerged across 22 sprints.
