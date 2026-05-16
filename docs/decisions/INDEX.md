# Architecture Decision Records — Index

Append-only history. One file per ADR. Read individual ADRs on demand via the filename links.

The numeric prefix (`0000`–`0026`) reflects **append order** in the original `DECISIONS.md`, not sprint chronology — Sprint 8.4 (0023) appears AFTER Sprint 8.2 CLOSE (0022) because that's how the history actually unfolded (Sprint 8.4 corrects 8.2 CLOSE's "baseline suspect" framing).

## Recent (chronological — most recent first)

- **0026** — [Sprint 6.4: sqlonfhir integration](0026-sprint-6-4-sqlonfhir-integration.md) (2026-05-15, shipped)
- **0024** — [Sprint 7.2: A2A FSM → LangGraph close-out](0024-sprint-7-2-a2a-fsm-closeout.md) (2026-05-15, **in-progress**)
- **0025** — [Sprint 8.3: Cost ceilings re-derived; Sprint 8 series closes](0025-sprint-8-3-cost-ceilings-re-derived.md) (2026-05-14, shipped)
- **0023** — [Sprint 8.4: Aggregator `cache_read` double-charge fix](0023-sprint-8-4-aggregator-cache-read-double-charge.md) (2026-05-14, shipped)
- **0022** — [Sprint 8.2 CLOSE: corrected baseline established](0022-sprint-8-2-close-corrected-baseline.md) (2026-05-14, shipped)
- **0021** — [Sprint 8.2: six-month silent prompt-caching bug](0021-sprint-8-2-prompt-caching-bug.md) (2026-05-14, shipped)
- **0020** — [Sprint 6.3 verdict revision: GO sqlonfhir](0020-sprint-6-3-verdict-revision-go-sqlonfhir.md) (2026-05-14, supersedes 0019)
- **0019** — [Sprint 6.3: DuckDB-FHIR verdict GO Pathling](0019-sprint-6-3-duckdb-fhir-verdict-go-pathling.md) (2026-05-14, **superseded** by 0020)
- **0018** — [Sprint 8.1: LangSmith as source-of-truth for LLM cost](0018-sprint-8-1-langsmith-cost-source-of-truth.md) (2026-05-12, shipped)
- **0017** — [Workflow: PR cadence — one squash PR per sprint](0017-workflow-pr-cadence.md) (shipped)
- **0014** — [Sprint 6.2 Phase 1.5: lambda-finish PROCEED gate](0014-sprint-6-2-phase-1-5-lambda-finish-proceed-gate.md) (2026-05-09, shipped)
- **0015** — [Sprint 6.2 Phase 2.5: MV router hardening](0015-sprint-6-2-phase-2-5-mv-router-hardening.md) (2026-05-08, shipped)
- **0013** — [Sprint 6.1 Phase 3a: TLS enforcement](0013-sprint-6-1-phase-3a-tls-enforcement.md) (2026-05-07, shipped)
- **0016** — [Sprint 6.1 Phase 3b: encryption-at-rest](0016-sprint-6-1-phase-3b-encryption-at-rest.md) (2026-05-07, shipped)
- **0012** — [Sprint 6.1 Phase 2.3: input validation framework](0012-sprint-6-1-phase-2-3-input-validation.md) (2026-05-04, shipped)
- **0011** — [Sprint 6.1 Phase 2.2: audit middleware fail-closed default-deny](0011-sprint-6-1-phase-2-2-audit-middleware.md) (2026-05-03, shipped)
- **0007–0010** — Sprint 6.1 series (HIPAA baseline, audit pipeline, split auth, doc reorg)
- **0001–0006** — Foundational sprints (4, 4.5, 5, 5.5, 6, 7)
- **0000** — [Meta: Recurring workflow pattern](0000-meta-recurring-workflow-pattern.md) (in-progress; observation note)

## By topic

### Data layer (Lambda Architecture / SQL-on-FHIR)

- [0002 — Sprint 4.5: Lambda batch layer via materialized views](0002-sprint-4-5-lambda-batch-materialized-views.md)
- [0004 — Sprint 5.5: Redis as Lambda speed layer](0004-sprint-5-5-redis-lambda-speed-layer.md)
- [0014 — Sprint 6.2 Phase 1.5: PROCEED to Phase 2 (transpiler gate cleared)](0014-sprint-6-2-phase-1-5-lambda-finish-proceed-gate.md)
- [0019 — Sprint 6.3: DuckDB-FHIR verdict GO Pathling (superseded)](0019-sprint-6-3-duckdb-fhir-verdict-go-pathling.md)
- [0020 — Sprint 6.3: verdict revision GO sqlonfhir](0020-sprint-6-3-verdict-revision-go-sqlonfhir.md)
- [0026 — Sprint 6.4: sqlonfhir integration + dispatch plumbing](0026-sprint-6-4-sqlonfhir-integration.md)

### Orchestration

- [0001 — Sprint 4: keep custom FSM + parallel LangGraph migration](0001-sprint-4-keep-custom-fsm-langgraph-parallel-target.md)
- [0006 — Sprint 7: LangGraph migration finalized](0006-sprint-7-langgraph-migration-finalized.md)
- [0024 — Sprint 7.2: A2A FSM close-out (in-progress)](0024-sprint-7-2-a2a-fsm-closeout.md)

### Security & compliance (Sprint 6.1)

- [0007 — HIPAA security baseline](0007-sprint-6-1-hipaa-security-baseline.md)
- [0008 — Durable audit pipeline via Redis queue](0008-sprint-6-1-audit-pipeline-redis-queue.md)
- [0009 — Split human/agent auth, not unified JWT](0009-sprint-6-1-split-human-agent-auth.md)
- [0010 — Documentation reorg (CLAUDE.md split + mattpocock skills)](0010-sprint-6-1-documentation-reorg.md)
- [0011 — Phase 2.2: audit middleware fail-closed default-deny](0011-sprint-6-1-phase-2-2-audit-middleware.md)
- [0012 — Phase 2.3: input validation framework](0012-sprint-6-1-phase-2-3-input-validation.md)
- [0013 — Phase 3a: TLS enforcement](0013-sprint-6-1-phase-3a-tls-enforcement.md)
- [0015 — Phase 2.5: MV router hardening (admin gate + view_name allowlist)](0015-sprint-6-2-phase-2-5-mv-router-hardening.md)
- [0016 — Phase 3b: encryption-at-rest](0016-sprint-6-1-phase-3b-encryption-at-rest.md)
- [0005 — Sprint 6: parameterized SQL via SQLAlchemy `text()`](0005-sprint-6-parameterized-sql.md)

### Cost telemetry & observability

- [0003 — Sprint 5: LangSmith for observability](0003-sprint-5-langsmith-observability.md)
- [0018 — Sprint 8.1: LangSmith as source-of-truth for LLM cost](0018-sprint-8-1-langsmith-cost-source-of-truth.md)
- [0021 — Sprint 8.2: six-month silent prompt-caching bug](0021-sprint-8-2-prompt-caching-bug.md)
- [0022 — Sprint 8.2 CLOSE: corrected baseline established](0022-sprint-8-2-close-corrected-baseline.md) (corrected by 0023)
- [0023 — Sprint 8.4: aggregator `cache_read` double-charge fix](0023-sprint-8-4-aggregator-cache-read-double-charge.md)
- [0025 — Sprint 8.3: cost ceilings re-derived; Sprint 8 series closes](0025-sprint-8-3-cost-ceilings-re-derived.md)

### Workflow & process

- [0017 — PR cadence: one cohesive squash PR per sprint](0017-workflow-pr-cadence.md)
- [0000 — Meta: Recurring workflow pattern (re-examining recommendations when premise may have shifted)](0000-meta-recurring-workflow-pattern.md)

## Conventions

**Append-only.** Corrections to a prior ADR go into a NEW ADR file that names what it supersedes or corrects (precedent: Sprint 8.4 corrects Sprint 8.2 CLOSE; Sprint 6.3 verdict revision supersedes Sprint 6.3 verdict). Don't edit an old ADR's body to change a claim — append a new one that explicitly names the correction.

**YAML frontmatter (every ADR file):**

```yaml
---
sprint: 6.4              # null for meta/workflow ADRs
date: 2026-05-15         # null when unknown (early sprints)
status: shipped          # shipped | in-progress | superseded | deprecated
supersedes: []           # list of "NNNN-...md" filenames this ADR supersedes
superseded_by: null      # filename if a later ADR supersedes this
related: []              # cross-reference filenames (non-supersession)
---
```

**Adding a new ADR.** Next number = highest existing number + 1. Filename pattern: `NNNN-sprint-X-Y-topic-slug.md` for sprint ADRs, `NNNN-topic-slug.md` for workflow/meta. Add the entry to both sections in this index.

**See also:** `docs/decisions/README.md` for the long-form conventions doc; `CLAUDE.md` for what auto-loads into Claude Code sessions.
