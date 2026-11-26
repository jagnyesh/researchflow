# ResearchFlow

ResearchFlow is a proof of concept for LLM-assisted clinical research data requests with human approval gates, run on synthetic patients. FastAPI + LangGraph + SQL-on-FHIR.

## Living state — read these for current context

- @CONTEXT.md — what is true *right now* (active sprint, in-progress work, blockers)
- @.claude/architecture.rules — naming conventions, agent patterns, no-go zones

Read these on demand (not auto-loaded, to keep every session's context small):

- `docs/decisions/INDEX.md` — append-only architecture decision log; one file per ADR under `docs/decisions/`. Before you change behavior in an area, read the index's "By topic" section, then the ADRs listed there for that area.
- `BACKLOG.md` — forward plan (upcoming sprints, decision gates). Read it when planning or choosing what to work on next.

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

For reports, PR bodies and review verdicts (added 2026-11-24): label each claim
**measured** (you ran it and saw the output), **inferred** (it follows from what
you read) or **guess**. Readers take an unlabeled claim as measured, so label
anything you did not run yourself. Labels go on the evidence, never on an
attestation's `- Verdict:` or `- Reviewed-Commit:` lines, which validate-and-ship
parses exactly.

For any measured number (added 2026-11-24; speedup, token count, eval score, cost): before
trusting, reporting or acting on it, name what limits it and rule out that it
measured something other than the intended work. Precedent: the Sprint 8.4
aggregator double-charged because `input_tokens` already includes
`cache_read` (ADR 0000 case 8).

For any change (added 2026-11-24): subtract before you add. Remove dead code and unused paths
first, take the smallest change that does the job, and prefer deletion to a new
abstraction. The ponytail skill (`.claude/skills/ponytail/SKILL.md`) holds the
detailed rules for code.

Full context with 10 documented cases: see [ADR 0000](docs/decisions/0000-meta-recurring-workflow-pattern.md)
"Recurring workflow pattern" in the ADR log.

## Throughput workflow: per-lane discipline

Full method: `docs/DAILY_DEV_WORKFLOW.md` (read on demand). These are the rules every lane inherits — a second autonomous lane sees only what is written here, not what lived in the last session. First run under this model was Sprint 6.7 (11 slices, one branch/PR each) — run serially, before the `scripts/lane.sh` harness existed; it proved continuous per-issue merge, not parallel lanes.

**Per-issue continuous merge (§2, §4.1).** One branch per issue (`feat/<issue>-<slug>` or `fix/<issue>-<slug>`), one PR per issue, attested squash-merge the moment it is green — by the merge actor the Merge actor rule below defines (human for behavior-touching PRs). No parking commits on a shared feature branch until sprint end. **Branch before editing** — slipped on #100 (committed to `main`, recovered non-destructively). The sprint is a planning + retro cadence, not a merge gate.

**The pipeline (§5).** Take a finished change from "code done" to "merged" with `/validate-and-ship`: /qa → fresh-context review → conventional commit → rebase onto main → PR with Testing Evidence → SHA-bound attestation comment → watch CI → merge by class (human unless standing rule) → escalate ambiguity only. Green unit tests alone never clear the bar; wire-level confirmation is required at interface boundaries (Sprint 8.2 langchain-anthropic, Sprint 8.4 aggregator).

**Delegation + review (§5.1) — required once lanes run in parallel:**
1. Delegate outcomes with the *why* attached, not step lists. The why lets a lane generalize and run longer without you.
2. **Review in a fresh context, not the authoring session.** The pipeline enforces this. Highest-leverage rule in the stack — a session grading its own homework assumes its own intent.
3. **Escalation split:** behavior-changing findings come to the human; mechanical findings (lint, naming, dead code) the lane fixes itself.
4. Don't take back control — teach. A lane error → feedback + memory write-back, not "I'll do it myself." Taking over makes you the bottleneck across every lane at once.

**Lane-close write-back (§5.1).** Before a lane relaunches, ask: "Did this lane do anything I had to correct? If yes, append one dated line stating the rule — with today's case as precedent — to CLAUDE.md or `.claude/architecture.rules`." A correction captured once fixes every future lane; skipping it re-teaches the same lesson in parallel.

**Project venv (added 2026-11-23).** Run all Python work through `.venv` (Python 3.11): `./.venv/bin/pytest`, `./.venv/bin/python`. Never `pip install` or `uv pip` into another environment; every `uv pip` command names `--python .venv/bin/python`. If `.venv` is missing, create it with the README "Quick start" commands, not the system or conda Python. `.claude/settings.json` asks before every `pip install` and `uv pip install`/`sync`, `.venv` ones included: a deliberate speed bump, since prefix rules can't tell the two apart (`python3.11 -m pip` and `uv --quiet pip` slip past it; the rule above still applies). In a lane worktree, the Stop hook reports the affected tests as not run when `.venv` is missing. Precedent: the #129 `healthcare_env` hijack, and on 2026-11-23 a cloud session's default `python3` (3.13) couldn't build `asyncpg`.

**Skill vetting (§9, the "§5.5 bar").** Before installing any skill or tool: read the whole `SKILL.md` and its bundled scripts (not the README); grep for network calls, `curl | bash`, credential/env access, and package installs; require a named maintainer and a pinned version/commit; trial command-executing skills in a throwaway repo first; never install mid-task because an agent suggested it — finish the task, then vet cold. Sandbox-first is a standing rule beyond skills (added 2026-07-19): anything that mutates filesystems or environments — our own scripts included — proves itself in a throwaway target first. Precedent: the 2026-07-18 `uv pip sync` hijack of the shared `healthcare_env` (#129).

**Vetting ledger:** `docs/audits/vetting-ledger.md` (read on demand). Standing consequences:
- lean-ctx is pinned to a source build of `v3.9.12`; never run `lean-ctx update` (even `--help` rewrites `~/.zshrc`, global CLAUDE.md and hooks). Upgrade only by rebuilding from a newer tag.
- ponytail is a copy-a-file pin @ `552acd5` with three local edits (2026-10-20 prompt audit); upgrade by re-fetch + re-diff, never the marketplace/plugin install.
- caveman (full system) is not adopted; the in-session `/caveman` skill covers output brevity.

**Guardrail (§3, §10).** The metric is *verified merges per week* (evidence section + green CI + fresh-context review), not raw merges. There is no lane cap (removed 2026-11-16). Three rules in `docs/DAILY_DEV_WORKFLOW.md` §3 still stop a launch; §10's dials (waiting PRs, High-tier lanes, plan limits, issue flow) are read at the `/plan-lanes` gate, and the owner decides from them. `scripts/dials.sh` computes the measurable cycle-time sub-intervals (open→green pipeline health, green→merge) per merge day; green→merge restarts on every push, so under strict protection it no longer measures how long a PR waited on you — `docs/DAILY_DEV_WORKFLOW.md` §3 has that measure.

**Merge actor (§1, §5; added 2026-07-19).** On green CI the pipeline reports and waits — a human merges every behavior-touching PR. Standing-rule exception: docs-only PRs (`docs:` prefix AND only `docs/**` or root-level `*.md` paths — a `.md` under `app/` or `tests/` is behavior-touching) and harness-internal PRs (only `.claude/**`, `scripts/lane.sh`, `scripts/dials.sh`, `docs/DAILY_DEV_WORKFLOW.md`, `CLAUDE.md`) may self-merge, with the squash commit carrying a visible `Merged-By: pipeline (standing-rule: <class>)` trailer. Self-amendment carve-out: a PR changing the merge policy itself (the validate-and-ship skill, this rule, the workflow doc's merge sections) is always human-merge. Either class merges only against a current SHA-bound attestation: a PR comment recording the review verdict and the exact reviewed commit SHA, equal to `headRefOid` at merge time and enforced with `gh pr merge --match-head-commit`. Only the repo owner's unedited comment counts as that attestation; read it with validate-and-ship Step 7.5, which refuses another account's or an edited one. A post-attestation push voids the attestation — fresh review + fresh comment, never a silent merge — except a merge from a commit on `origin/main` whose resulting tree exactly equals `git merge-tree` of the last real (SHIP) review's commit and that main commit (no file changed on both sides), which carries the attestation forward in a new comment that is re-checked before merge (validate-and-ship Steps 7.4 and 8; added 2026-11-07, #361). The attestation is also a commit status named `attestation`, set on each PR's head by `.github/workflows/attestation.yml`. Once it is a required check on `main`, GitHub refuses any merge without a current attestation, and, once the owner allows auto-merge, standing-rule PRs merge through `gh pr merge --auto` (validate-and-ship Steps 7.6 and 8; added 2026-11-13, #466). Precedent: the 2026-07-19 last-10-PR audit found 0/10 PRs carried an independent review artifact and the merge actor was undefined (#128).

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool.

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
- Ship a finished change / open + merge its PR → invoke /validate-and-ship (repo pipeline; not /ship)
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
