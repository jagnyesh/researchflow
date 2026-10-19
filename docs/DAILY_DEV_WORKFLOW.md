# Daily Agentic Development Workflow — Risk-Tiered Edition

**Status:** current workflow doc — supersedes the prior *Throughput Edition* (pre-2026-10 version lives in git history). One workflow doc only, by design (two is drift).
**Recast for:** everyday coding on ResearchFlow, optimized for *verified* merges per week.
**What changed from the prior (Throughput) edition:** planning weight is now **conditional on risk**, not uniform; the social rules (fresh-context review, test integrity) get **mechanical enforcement**; the uncorroborated external "68%" stat is **replaced by a metric you measure here**; parallelism is marked **never-yet-exercised in this repo**; sourcing leans on the primary Anthropic *AI-Native SDLC* course rather than an unverifiable secondary synthesis.

---

## 0. Measure before you theorize

This doc's claims are only as good as the repo's own numbers. Before adding a lane, a gate, or a rule, pull the real data:

- `scripts/dials.sh` — open→green (pipeline health) and green→merge (merge-gate latency), per merge d
- Review-minutes per PR and the **catch-rate log** (§6) — the real optimization target.
- Honest baseline, recorded here so nobody mistakes aspiration for practice: **parallel lanes have never run in this repo.** Sprint 6.7's 11 slices shipped *serially*, before `scripts/lane.sh` existed. Everything in §4 about multiple lanes is therefore design intent, not observed steady-state. Treat §4 as untested until the §3 trigger actually fires and you log a week of it.

---

## 1. The spine: one risk classifier drives everything

The single structural idea in this edition. A change's **risk tier** — decided by the paths it touches — sets its planning weight, its protected files, whether it hits the eval gate, and who merges it. This extends the merge-by-class path rule you already run; it does not invent a parallel system, but the high-risk path set below is genuinely new and domain-specific, so it earns real judgment, not a copy-paste.

| Tier | What's in it (ResearchFlow paths) | Planning weight | Merge actor | Eval gate | Golden files |
|---|---|---|---|---|---|
| **High** | PHI boundary / `SQLValidator` (aggregate-only gate); cohort & phenotype semantics — `app/services/sql_synthesis.py`, `app/agents/phenotype_agent.py`, `app/services/feasibility_service`, `app/agents/extraction_agent.py`; auth / RBAC / audit — `app/security/**`; encryption; IRB-scope logic; the golden fixtures themselves | Full `grill-with-docs` → design doc → ADR | **Human**, always | **Required if LLM-touching** (§5); otherwise rigor comes from the grill→design→ADR chain + always-human merge + locked goldens | Locked |
| **Medium** | Behavior changes *outside* high-risk paths — portal UI (non-SQL), non-PHI API endpoints, runner plumbing (`app/sql_on_fhir/runner/**`), orchestration wiring, dev scripts | 5–10 line **intent block in the PR body** (what / why / constraints / non-goals) | Human | If LLM-touching (§5), else no | n/a |
| **Low** | docs-only; test-only (non-golden); pure refactors with no behavior change outside high-risk paths; harness-internal (`.claude/**`, `scripts/lane.sh`, `scripts/dials.sh`, workflow docs) | The issue body **is** the intent — no extra artifact | Standing-rule **self-merge** (`Merged-By` trailer, SHA-bound attestation) | no | n/a |

Three consequences this settles:

- **The plan-mode debate dissolves.** "How much to write down" was never one answer. High-risk work earns the full grill→design→ADR chain because a wrong cohort definition or PHI-boundary assumption is expensive and auditable — the 2026 plan-mode discourse's "let the model make reasonable assumptions" posture (Nadeem) is exactly what you refuse *here*, while the course itself prescribes the opposite for risky work ("interrogate the plan: what could it break, which step is riskiest, what did Claude rule out"). Low-risk work gets nothing but the issue body, because a persisted artifact there only drifts. Medium risk gets the course's `intent.md` content *inlined in the PR* so there's no new file to go stale.
- **Blast radius, not autonomy duration, is the justification.** The Throughput Edition argued plan depth from "autonomy duration" (contested, and refuted by the 2026 plan-mode discourse). This edition argues it from blast radius and auditability — which actually holds in a clinical/regulatory codebase and is the defense that edition never made.
- **Golden files are the real test-integrity surface** — not all of `tests/**`. See §7.

**Where the playbook's artifact chain actually lives.** This doc commits no `intent.md`/`spec.md`/`plan.md` — a deliberate substrate choice, not an omission. The chain runs, routed through the issue tracker and the ADR log, which drift less than committed spec files in a solo repo:

| Playbook artifact | Role | Here | Lives in |
|---|---|---|---|
| `intent.md` | capture problem / why / constraints | `/to-prd` | GitHub issue (`needs-triage`) — the skill forbids file paths to avoid staleness |
| `spec.md` | requirements + design | `/spec` | GitHub issue — closed on merge |
| `plan.md` | files / order / risks / proof | `/tdd` + plan mode | in-session; high-risk persists as a design doc → ADR |
| — *(ongoing)* | the durable "why" | ADRs via `/grill-with-docs` | `docs/decisions/` — committed, point-in-time stamped |
| — *(state)* | current truth | `CONTEXT.md` | committed |

The one playbook practice this substrate would otherwise drop — *"check the diff against the committed plan"* — is restored as a review step, not a file (§5).

---

## 2. The evergreen core (proven; unchanged)

These two moves are the win, and Sprint 6.7 proved them — serially, no parallelism required:

1. **Validation is one autonomous pipeline** (`/validate-and-ship`, §5), not a hand-run `/qa` + `/review` + `/ship` chain.
2. **Merging is continuous** — one branch per issue, one PR per issue, merged the moment it's green by the tier's merge actor. The sprint is a planning + retro cadence, not a merge gate.

The binding constraint on everything else is **how many review streams one person can sustain**, and it is **model-independent**: faster models produce more to review, not more attention to review it with. (Anthropic *AI-Native SDLC* course: *"The practical ceiling is how many streams one person can review properly, so add sessions only while review is keeping up."*)

---

## 3. The ramp (parallelism is optional and, here, unproven)

**Stages 0–1 are done** (pipeline + continuous merge, proven across 6.7). **Stages 2–3 are trigger-gated and have never fired in this repo** — do not climb for its own sake.

**Stage 0 — Foundations.** Voice input (§8), the risk classifier (§1), memory write-back (§5.3-equivalent below), evidence-PR template (§6), skill vetting (§9). CI runs real tests on every PR.

**Stage 1 — The pipeline.** `/validate-and-ship` end to end; per-issue branches; continuous merge. *Exit:* three consecutive issues where your only post-handoff involvement was escalated decisions.

**Stage 2 — Two lanes (only when the trigger fires).** *Trigger:* a lane is mid-run on a long autonomous task **and** a second independent, well-specified issue is ready **and** review is keeping up. If any clause is false, a second lane is negative throughput (§10). *Substrate, lightest first:* native `claude --worktree <name>` → `scripts/lane.sh` (WIP guard + dep-sync) → raw `git worktree`. WIP = 2. *Exit:* one logged week where no PR waited on you > 1 day.

**Stage 3 — Scale.** 3–5 lanes; native worktrees + background/cloud agents before any external pool tool. No external worktree-pool or "overnight" binary unless it clears §9. *Exit:* none — cruising altitude, only while §10 holds.

---

## 4. The daily workflow

### 4.1 Single-lane issue loop (the current, complete mode)

```
branch per issue           → fix/<issue> or feat/<issue>  (branch BEFORE editing)
classify (§1)              → tier sets planning weight + merge actor + gate
plan to tier               → low: none · medium: PR intent block · high: grill→design→ADR
/tdd                       → tests committed BEFORE implementation, then LOCKED (§7)
/diagnose                  → if stuck >20 min; wire-level empirical confirmation first
/validate-and-ship (§5)    → qa → fresh-context review (CI) → commit → rebase → PR w/
                             evidence → SHA-bound attestation → CI (incl. eval gate if
                             LLM-touching) → merge by tier
merge                      → human for high/medium; standing-rule self-merge for low
write-back                 → any correction this change needed → one dated line in
                             CLAUDE.md before the next issue
```

### 4.2 Multi-lane day shape — ASPIRATIONAL (never exercised here)

> Adopt only after the §3 Stage-2 trigger fires and you've logged it. Until then this is design intent, not your workflow.

PLAN (fill queue to lanes × 2) → LAUNCH (one agent per lane) → MANAGE (review evidence, answer escalations, merge greens) → WRITE-BACK.

### 4.3 Sprint start = queue-fill cadence

`/grill-with-docs` → design doc (**for high-risk deliverables**) → `/to-issues` → 5–10 vertical slices labeled `ready-for-agent`, **each pre-classified by tier**. Plan quality still buys autonomy — but spend it where blast radius warrants, not uniformly.

### 4.4 Sprint end = quality + learning event

`/improve-codebase-architecture` (entropy pass) → `/qa` (integration-level) → `/retro` (15 min, append ADR). Merging already happened continuously; sprint end verifies the *whole*, not slices.

---

## 5. The composite pipeline — `/validate-and-ship`

One invocation, "code done" → "merged or escalated":

1. `/qa` on the change.
2. **Fresh-context review as a CI check** (§7) — a clean reviewer, non-interactive, posting **one consolidated verdict** (never a comment stream; that spends the §10 bandwidth it's meant to save). For **high-tier** changes the reviewer also asserts the diff matches the approved design doc / ADR, and that any departure is recorded in this PR — the playbook's plan-vs-reality discipline (check the diff against the committed plan; when it departs, update the plan in the same commit), applied to the ADR instead of a `plan.md`.
3. Apply mechanical fixes; **escalate behavior-changing findings** to the human.
4. Conventional commit on the issue branch; rebase onto latest `main`.
5. Push; open PR with the Testing-Evidence section filled from step 1's real output.
6. Post the **SHA-bound review attestation** (step 2's consolidated verdict + reviewed commit SHA == `headRefOid`).
7. **Eval gate** runs iff the change is LLM-touching (§5-trigger); CI runs real tests (needs the docker-compose test job live).
8. On green, **merge by tier** (§1): human reads the consolidated verdict and signs for high/medium; low self-merges under the standing rule with `--match-head-commit`.

**LLM-touching trigger for the eval gate** — the surfaces that actually call a model, named correctly (not the retired `query_interpreter.py`):

- `app/services/sql_synthesis.py` (exploratory NL→SQL synthesis — #76 territory),
- `app/agents/requirements_agent.py` (concept extraction),
- `app/utils/llm_client.py` / `app/utils/multi_llm_client.py` and anything calling them (incl. `calendar_agent` / `delivery_agent` via `langgraph_workflow`),
- any prompt or model-config file.

The gate uses `#136`/`#137`/`#142`'s harnesses, sets **per-domain thresholds**, runs on those paths + nightly, and **asserts it executed N cases** — an eval that passes on zero cases is worse than none (TODOS already records one integration job that was silently a no-op).

**Attestation reconciliation:** the CI reviewer *produces* the verdict; it does not *become* the merge actor. For high/medium a human still reads the consolidated verdict and merges — the attestation records a human sign-off. For low, the CI verdict + SHA-bound comment is itself sufficient to self-merge. This keeps the merge-governance the Throughput Edition got right intact.

### 5.3 Delegation + memory (unchanged principles)

Delegate outcomes with the *why*. Never review in the authoring session (now mechanized, §7). Escalation split: behavior → human, mechanical → the agent. Don't take back control — teach via a dated CLAUDE.md line. **Lane-close check:** "Did this change need a correction? If yes, one dated rule-line in CLAUDE.md before the next issue."

---

## 6. The metric is yours, measured — not a borrowed stat

The Throughput Edition leaned on an external, uncorroborated "68% of agent changes carried bugs." This edition deletes it and measures the equivalent **here**:

- **Catch-rate log:** tag what the fresh-context review catches before merge.
- **Escape-rate:** reverts, reopened issues, and bugs filed against recently-merged PRs.
- **Review-minutes per PR.**

Together these are the **reviewer-hour** picture your own principles call the real target, and the honest evidence for the WIP limit — not a blog post. **Verified merge = evidence section + green CI (+ eval gate if LLM-touching) + consolidated fresh-context verdict.** Unverified merges are inventory of future rework; the faster the models, the faster that inventory accrues, so this matters *more* as capability rises.

**Evidence-bearing PR template:**

```markdown
## Testing evidence
- Risk tier: <low|medium|high> — paths: <...>
- Commands run: `pytest ... -x` → N passed / 0 failed
- E2E exercised: <what was driven; expected vs observed>
- Eval gate (if LLM-touching): <N cases asserted; per-domain scores>
- Artifacts: <AppTest output | LangSmith trace URL | verbatim output; text only>
- Not covered: <gaps and why acceptable>
```

---

## 7. Mechanical enforcement (and its price)

The sharpest rules were social; mechanize them — but **every new mechanism is itself §9 surface + maintenance + a drift/no-op risk, so prefer the lightest enforcement that works and make each gate prove it ran.** "Simpler wins" applies to your own rig, not just the agent's.

- **Test integrity — protect golden files, not all `tests/**`.** The high-value targets are `tests/fixtures/transpiler_expected_outputs.py` and the gate `.jsonl` sets (`logs/sprint_*_gate.jsonl`). "Regenerate expected outputs to match" is exactly how a #76-style silent bug passes. Rule (works under `/tdd`, where the agent writes the tests): **tests are committed before implementation and locked from then until the task ends.** Enforce with the lightest equivalent — a CI diff check on the golden paths over a PreToolUse hook if the CI check suffices.
- **Fresh-context review is a CI check** (§5 step 2), one consolidated verdict.
- **Drift at its source.** Status claims — node counts, test counts, "shipped" markers — are **generated or checked by a script**, never hand-typed into CLAUDE.md / CONTEXT.md / issues. (The Throughput Edition's "23-state vs 17-nodes" and "12 vs 1 integration tests" were status drift, not design-doc drift — lighter planning would not have prevented them; generated counts would.) Design docs and ADRs are stamped **point-in-time** so nobody reads them as current state.

---

## 8. Voice input

You talk faster than you type, and the cost of attaching the *why* drops to near zero. At planning volume this is the difference between thin and deep plans. macOS: OpenSuperWhisper (local Whisper, hotkey) or built-in dictation. Voice for intent/context/plans; keyboard for identifiers, paths, code.

---

## 9. Skill / tool vetting (§5.5 bar, unchanged)

Before any skill or executing tool: read the whole `SKILL.md` **and** bundled scripts; grep for network calls, `curl | bash`, credential/env access, package installs; require a named maintainer + pinned version/commit; trial command-runners in a throwaway repo; never install mid-task on an agent's suggestion — finish, then vet cold. **This bar applies to the mechanisms in §7 too** — a test-lock hook or eval-gate script is tooling you must vet and maintain, not free safety.

---

## 10. Throughput guardrails

- **Verified merges per week** (defined in §6) — the only merge count that matters.
- **Cycle time** (`dials.sh`): plan-handoff → merge. Ballooning means thin plans or over-escalation — fix before adding lanes.
- **WIP = review streams you can actually unblock.** Model-independent ceiling. Scale to N+1 only when escalations-per-lane are low and nothing waits overnight.
- **Review-debt rule:** no new lane while ≥ 2 PRs await your decision.
- **Never scale past validation:** pipeline red/flaky → one lane until green.
- **Queue health:** refill to lanes × 2; starvation means the plan block was thin.
- **The memory loop is the ceiling-raiser:** write-backs, ADRs, retros, generated status — the compounding practices are what make month three faster than month one.

---

## 11. Not adopted — and the honest cons

- **Editor/terminal migration (Neovim/WezTerm):** downstream of muscle memory, not the source of speed. Skip.
- **Production Maintain loop (course Stage 6):** there is **no production deployment yet**, so the prod-anomaly→replan loop doesn't apply literally. The version that *does*: post-merge signals you already have — nightly CI failures, eval regressions, cost/drift telemetry (#151), LangSmith traces — **auto-file issues into the queue**. Build that, not the prod loop.
- **The planning stance is a position, not a law.** The 2026 plan-mode discourse (Nadeem's "plan mode is dead"; instil's "spec-driven dead, long live plan mode") is ~a handful of posts over a month, mostly about general work where output is cheap to check — not a consensus, and not obviously transferable to PHI/cohort work. This edition's risk tiering is the hedge: it refuses heavy artifacts where they'd only drift (low/medium) and keeps them where blast radius is real (high). If your measured catch-rate (§6) ever shows high-tier grilling isn't catching more than medium-tier intent blocks, revisit this.

---

## 12. Cheat sheet

| Moment | Chain | Rule |
|---|---|---|
| New issue | classify (§1) → plan to tier | low: none · medium: PR intent block · high: grill→design→ADR |
| Build | `/tdd` → **/validate-and-ship** | tests committed + locked before impl (§7) |
| Stuck > 20 min | `/diagnose` | wire-level empirical confirmation first |
| PR | evidence template (§6) + SHA-bound attestation | tier sets merge actor |
| Merge | by tier | human for high/medium; low self-merges (`--match-head-commit`) |
| LLM-touching change | eval gate (§5) | per-domain thresholds; assert N cases ran |
| Lane close | memory write-back if corrected | one dated CLAUDE.md line |
| Sprint end | `/improve-codebase-architecture` → `/qa` → `/retro` | ADR appended, point-in-time stamped |
| New skill/mechanism | §9 vetting | read everything; pin; never mid-task |
| Scaling check | §10 | escalations low + no review debt + CI green |

---

*Sourcing note:* practices corroborated primarily by Anthropic's *AI-Native SDLC Playbook* (academy.claude.com) and triangulated against the 2026 plan-mode discourse. No load-bearing claim rests on an unverifiable secondary source; the one quantitative claim (§6) is measured in this repo, not imported.
