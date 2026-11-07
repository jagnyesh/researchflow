# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — current state, domain vocabulary, active sprint, in-progress work
- **`docs/decisions/INDEX.md`** — the index of **this project's ADR (architecture decision record) log**, most recent first and by topic. Each decision is its own file, `docs/decisions/NNNN-<slug>.md`. Read the ADRs that touch the area you're about to work in.
- **`BACKLOG.md`** at the repo root — forward plan + filed follow-ups

**Flag missing files explicitly — do NOT proceed silently.** If `CONTEXT.md` or `BACKLOG.md` doesn't exist in this repo specifically, that's an anomaly — these files are foundational and should always be present. The skill seed templates' general "proceed silently" rule is for projects where these conventions haven't been established yet; ResearchFlow has had them since Sprint 4. Their absence likely means an accidental deletion, a partial checkout, or a tree-corruption event worth surfacing before continuing.

## ADR location (READ THIS BEFORE LOOKING IN `docs/adr/`)

The Matt Pocock skills' default convention puts per-decision ADR files under `docs/adr/`. ResearchFlow keeps them under `docs/decisions/` instead, one file per decision, numbered in append order. The filename pattern, the YAML frontmatter and the append-only rule (a correction is a new ADR that names what it corrects) are in `INDEX.md`'s Conventions section.

CLAUDE.md `@`-imports `docs/decisions/INDEX.md`, so the index auto-loads every session; read individual ADRs on demand. The log used to be a single root `DECISIONS.md`; #90 deleted its last stub on 2026-05-24. Older docs and code comments still cite that file by name; read those mentions as the matching file under `docs/decisions/`.

When a skill says "read ADRs that touch this area," start from the index's "By topic" section, then grep `docs/decisions/` for the area's domain terms (e.g. `LangGraph`, `HybridRunner`, `cost_telemetry`, `audit middleware`).

## File structure

Single-context. One `CONTEXT.md` at the root. One ADR log under `docs/decisions/`. One `BACKLOG.md` at the root. No `CONTEXT-MAP.md`, no `docs/adr/`, no monorepo splits.

```
/
├── CLAUDE.md                  ← bootstraps + imports CONTEXT, the ADR index, BACKLOG
├── CONTEXT.md                 ← living state, domain vocabulary
├── BACKLOG.md                 ← forward plan + follow-ups
├── docs/decisions/            ← append-only ADR log, one file per decision
│   └── INDEX.md               ← index: most recent first, then by topic
├── docs/architecture/         ← architectural snapshots (frozen at timestamp)
└── app/                       ← code
```

`docs/architecture/` is append-only by convention — never overwrite an existing snapshot. New snapshots get a new dated filename (e.g. `05-15architecturereview.md`). This preserves the historical sequence of zoom-out views so future agents can see how the architecture evolved.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

Examples of canonical terms:
- **Formal Portal** / **Exploratory Portal** (NOT "formal app" / "exploratory app")
- **HybridRunner** / **MaterializedViewRunner** / **SpeedLayerRunner** (the Lambda Architecture stack)
- **Cost Telemetry** (NOT "cost dashboard" — the latter is the *consumer*, the former is the *service*)
- **Sprint gate** (pre-committed numeric criterion that fires sprint completion)

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR 0020 (Sprint 6.3 verdict revision: GO sqlonfhir) — but worth reopening because…_

Cite an ADR by its number, linked to its file with a path relative to the citing file (`docs/decisions/NNNN-<slug>.md` from a root-level file, `NNNN-<slug>.md` from another ADR), and add the sprint when it has one.

---

_Generated 2026-05-15 by `/setup-matt-pocock-skills`. Re-run only when switching issue trackers or restarting from scratch; edit this file directly for ongoing convention changes._
