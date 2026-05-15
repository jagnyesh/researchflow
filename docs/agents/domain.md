# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — current state, domain vocabulary, active sprint, in-progress work
- **`DECISIONS.md`** at the repo root — **this project's ADR log** (one append-only file, NOT per-decision files under `docs/adr/`). Each ADR entry is headed by a sprint number; the file is in chronological-append order with the most recent decision at the bottom. Read entries that touch the area you're about to work in.
- **`BACKLOG.md`** at the repo root — forward plan + filed follow-ups

**Flag missing files explicitly — do NOT proceed silently.** If any of `CONTEXT.md`, `DECISIONS.md`, or `BACKLOG.md` don't exist in this repo specifically, that's an anomaly — these files are foundational and should always be present. The skill seed templates' general "proceed silently" rule is for projects where these conventions haven't been established yet; ResearchFlow has had them since Sprint 4. Their absence likely means an accidental deletion, a partial checkout, or a tree-corruption event worth surfacing before continuing.

## Non-standard ADR location (READ THIS BEFORE LOOKING IN `docs/adr/`)

This project does NOT use `docs/adr/0001-*.md` per-decision files. The Matt Pocock skills' default convention assumes per-file ADRs; ResearchFlow uses a single append-only `DECISIONS.md` at the repo root with one entry per sprint. The file spans Sprint 4 through current.

Why: CLAUDE.md `@`-imports `DECISIONS.md` directly so its content auto-loads into the agent's context every session. Per-file ADRs would defeat that pattern. See CLAUDE.md's "Living state" section and the Sprint 6.1 "Documentation reorg" ADR in DECISIONS.md.

When a skill says "read ADRs that touch this area," grep DECISIONS.md for the area's domain terms (e.g. `LangGraph`, `HybridRunner`, `cost_telemetry`, `audit middleware`).

## File structure

Single-context. One `CONTEXT.md` at the root. One `DECISIONS.md` at the root. One `BACKLOG.md` at the root. No `CONTEXT-MAP.md`, no `docs/adr/`, no monorepo splits.

```
/
├── CLAUDE.md                  ← bootstraps + imports CONTEXT/DECISIONS/BACKLOG
├── CONTEXT.md                 ← living state, domain vocabulary
├── DECISIONS.md               ← append-only ADR log (single file)
├── BACKLOG.md                 ← forward plan + follow-ups
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

> _Contradicts the Sprint 6.3 spike GO sqlonfhir verdict in DECISIONS.md — but worth reopening because…_

Cite the sprint number when referencing DECISIONS.md entries (e.g. "Sprint 6.1 — Durable audit pipeline via Redis queue") since the file isn't numbered ADR-0001-style.

---

_Generated 2026-05-15 by `/setup-matt-pocock-skills`. Re-run only when switching issue trackers or restarting from scratch; edit this file directly for ongoing convention changes._
