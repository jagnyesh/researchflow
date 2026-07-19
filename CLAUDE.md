# ResearchFlow

AI-powered multi-agent system that automates clinical research data requests from natural language to delivery. FastAPI + LangGraph + SQL-on-FHIR. Reduces data request turnaround from weeks to hours.

## Living state — read these for current context

- @CONTEXT.md — what is true *right now* (active sprint, in-progress work, blockers)
- @docs/decisions/INDEX.md — append-only architecture decision log; one file per ADR under `docs/decisions/`
- @BACKLOG.md — forward plan (upcoming sprints, decision gates)
- @.claude/architecture.rules — naming conventions, agent patterns, no-go zones

Historical sprint reports live in `docs/sprints/archive/`. Don't load them unless explicitly asked.

## Operating discipline: re-examine recommendations when premise may have shifted

Before accepting an agent recommendation as final, ask: "what would have to be
true for this verdict to be wrong?" Read the cons/concerns section of any
recommendation twice as carefully as the pros section — the load-bearing
hand-waved assumption usually lives in the cons.

For diagnostic work: default to empirical confirmation (read the wire, dump
runtime state, inspect actual values) before scoping fixes. Static analysis
is insufficient for bugs at interface boundaries (wrappers, third-party APIs,
async layers, caching). The Sprint 8.2 langchain-anthropic silent transmission
bug and the Sprint 8.4 aggregator double-charge bug both ran for months
specifically because tests asserted at the wrapper layer, not the wire layer.

For verdict decisions: pre-commitments defend against bias, not against
information. When new information reveals a pre-commit's premise was broken,
deliberate override is appropriate when documented. Precedent: Sprint 6.2
Phase 1.5 Q1 refinement; Sprint 6.3 verdict revision GO sqlonfhir.

Full context with 10 documented cases: see [ADR 0000](docs/decisions/0000-meta-recurring-workflow-pattern.md)
"Recurring workflow pattern" in the ADR log.

## Throughput workflow: per-lane discipline

Full method: `docs/DAILY_DEV_WORKFLOW.md` (read on demand). These are the rules every lane inherits — a second autonomous lane sees only what is written here, not what lived in the last session. First run under this model was Sprint 6.7 (11 slices, one branch/PR each).

**Per-issue continuous merge (§4.2).** One branch per issue (`feat/<issue>-<slug>` or `fix/<issue>-<slug>`), one PR per issue, attested squash-merge the moment it is green — by the merge actor the §5.8 rule below defines (human for behavior-touching PRs). No parking commits on a shared feature branch until sprint end. **Branch BEFORE editing** — slipped on #100 (committed to `main`, recovered non-destructively). The sprint is a planning + retro cadence, not a merge gate.

**The pipeline (§5.8).** Take a finished change from "code done" to "merged" with `/validate-and-ship`: /qa → fresh-context review → conventional commit → rebase onto main → PR with Testing Evidence → SHA-bound attestation comment → watch CI → merge by class (human unless standing rule) → escalate ambiguity only. Green unit tests alone never clear the bar; wire-level confirmation is required at interface boundaries (Sprint 8.2 langchain-anthropic, Sprint 8.4 aggregator).

**Delegation + review (§5.2) — non-negotiable once lanes run in parallel:**
1. Delegate outcomes with the *why* attached, not step lists. The why lets a lane generalize and run longer without you.
2. **Never review in the authoring session.** Reviews run in a fresh context; the pipeline enforces this. Highest-leverage rule in the stack — a session grading its own homework assumes its own intent.
3. **Escalation split:** behavior-changing findings come to the human; mechanical findings (lint, naming, dead code) the lane fixes itself.
4. Don't take back control — teach. A lane error → feedback + memory write-back, not "I'll do it myself." Taking over makes you the bottleneck across every lane at once.

**Lane-close write-back (§5.3).** Before a lane relaunches, ask: "Did this lane do anything I had to correct? If yes, append one dated line stating the rule — with today's case as precedent — to CLAUDE.md or `.claude/architecture.rules`." A correction captured once fixes every future lane; skipping it re-teaches the same lesson in parallel.

**Skill vetting (§5.5).** Before installing any skill or tool: read the whole `SKILL.md` and its bundled scripts (not the README); grep for network calls, `curl | bash`, credential/env access, and package installs; require a named maintainer and a pinned version/commit; trial command-executing skills in a throwaway repo first; never install mid-task because an agent suggested it — finish the task, then vet cold. Sandbox-first is a standing rule beyond skills (added 2026-07-19): anything that mutates filesystems or environments — our own scripts included — proves itself in a throwaway target first. Precedent: the 2026-07-18 `uv pip sync` hijack of the shared `healthcare_env` (#129).

**Vetting ledger** (tool · version · vet date · verdict):
- lean-ctx · 3.9.12, floating (unpinned, unchecksummed stripped release binary from `releases/latest` — source-available upstream, binary provenance unverifiable; self-update capable) · 2026-07-19 · **FAIL** — pseudonymous maintainer, unpinned, `curl | bash` installer, hook-level rewrite of every Bash call; telemetry/cloud/proxy observed off. Retroactive vet (#132); in use pending a human keep/pin/remove decision (resolved same day — next entry). Full report: `docs/audits/2026-07-19-pipeline-audit.md`.
- lean-ctx · 3.9.12, **pinned — self-built from source** (tag `v3.9.12` = commit `54e0a66`, `cargo build --release --locked`, rustc 1.97.1 — same command/features/lockfile as upstream release CI; installed sha256 `dba8532b61c46c3a4411721e22373362015c6259bd3b1237696df20d9bd4678a`; release binary retained as rollback) · 2026-07-19 · **decision: PIN** (#134), sandbox-verified per the sandbox-first rule. Update checks disabled in BOTH config files (XDG `~/.config/lean-ctx` + legacy `~/.lean-ctx` — config split-brain: MCP reads the former, hooks/CLI the latter) plus `LEAN_CTX_NO_UPDATE_CHECK` in the MCP env; no autoupdate LaunchAgent. **`lean-ctx update` is a no-go command** — even `update --help` executes the full setup rewire (missing help guard at `rust/src/cli/dispatch/mod.rs:669`; observed 2026-07-19 rewriting `~/.zshrc`, global CLAUDE.md, hooks). Upgrades happen by rebuilding from a newer tag, deliberately. The floating risk was live: the binary had self-updated 3.5.14→3.9.12 at 01:09 that same morning. Residuals: pseudonymous maintainer; crates.io transitive chain (Cargo.lock-pinned); no full source audit.

**Guardrail (§7).** The metric is *verified merges per week* (evidence section + green CI + fresh-context review), not raw merges. Never scale lanes past validation: pipeline red or flaky → drop to one lane until green. No new lane launches while ≥2 PRs sit awaiting your decision. `scripts/dials.sh` computes the measurable cycle-time sub-intervals (open→green pipeline health, green→merge merge-gate latency) per merge day.

**Merge actor (§5.8, added 2026-07-19).** On green CI the pipeline reports and waits — a human merges every behavior-touching PR. Standing-rule exception: docs-only PRs (`docs:` prefix AND only `docs/**` or root-level `*.md` paths — a `.md` under `app/` or `tests/` is behavior-touching) and harness-internal PRs (only `.claude/**`, `scripts/lane.sh`, `scripts/dials.sh`, workflow docs) may self-merge, with the squash commit carrying a visible `Merged-By: pipeline (standing-rule: <class>)` trailer. Self-amendment carve-out: a PR changing the merge policy itself (the validate-and-ship skill, this rule, the workflow doc's merge sections) is always human-merge. Either class merges only against a current SHA-bound attestation: a PR comment recording the review verdict and the exact reviewed commit SHA, equal to `headRefOid` at merge time and enforced with `gh pr merge --match-head-commit`. A post-attestation push voids the attestation — fresh review + fresh comment, never a silent merge. Precedent: the 2026-07-19 last-10-PR audit found 0/10 PRs carried an independent review artifact and the merge actor was undefined (#128).

## Quick start

```bash
# Setup (one-time)
python3 -m venv .venv && source .venv/bin/activate
uv pip sync config/requirements.lock
cp config/.env.example .env  # add ANTHROPIC_API_KEY, REDIS_URL
pre-commit install

# Daily loop
redis-server &                                                 # speed layer
python scripts/materialize_views.py                            # batch layer (one-time/nightly)
streamlit run app/web_ui/research_notebook.py --server.port 8501   # exploratory UI
streamlit run app/web_ui/researcher_portal.py --server.port 8502   # formal request UI
streamlit run app/web_ui/admin_dashboard.py --server.port 8503     # admin
make run                                                       # API at :8000

# Tests + security
pytest -xvs
pre-commit run --all-files
bandit -r app/
```

Docker: `make docker-up` (postgres + mock FHIR + app).

## Service ports

| Service | Port | File |
|---|---|---|
| Exploratory Analytics (chat) | 8501 | `app/web_ui/research_notebook.py` |
| Formal Request Portal (form) | 8502 | `app/web_ui/researcher_portal.py` |
| Admin Dashboard | 8503 | `app/web_ui/admin_dashboard.py` |
| API | 8000 | `app/main.py` |
| Mock FHIR | 8080 | docker-compose |
| Postgres | 5432 | docker-compose |

## Key directories

- `app/agents/` — 6 specialized agents (Requirements, Phenotype, Calendar, Extraction, QA, Delivery), all `BaseAgent` subclasses
- `app/orchestrator/` — custom A2A orchestrator + 15-state workflow FSM (production)
- `app/langchain_orchestrator/` — LangGraph migration (23-state FSM, behind `USE_LANGGRAPH_WORKFLOW` flag)
- `app/sql_on_fhir/runner/` — Lambda Architecture: `materialized_view_runner.py` (batch) + `speed_layer_runner.py` (Redis) + `hybrid_runner.py` (serving)
- `app/database/models.py` — 6 tables (ResearchRequest, RequirementsData, FeasibilityReport, AgentExecution, Escalation, DataDelivery)
- `app/security/` — JWT auth, RBAC, rate limiting, audit logging (Sprint 6.1 active work)
- `tests/` — pytest with `pytest-asyncio`; subdirs `e2e/`, `integration/`, `security/`

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate or /diagnose
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Token-tight responses → invoke /caveman
- Validate plan/doc against reality → invoke /grill-with-docs

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (`jagnyesh/researchflow`). Skills use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). All five labels exist in the repo. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout. `CONTEXT.md` at the root for domain vocabulary; `docs/decisions/` for the append-only ADR log (one file per decision, indexed at `docs/decisions/INDEX.md`). See `docs/agents/domain.md`.
