# Daily Agentic Development Workflow — Risk-Tiered Edition

**Status:** current workflow doc — supersedes the prior *Throughput Edition* (pre-2026-10 version lives in git history). One workflow doc only, by design (two is drift).
**Recast for:** everyday coding on ResearchFlow, optimized for *verified* merges per week.
**What changed from the prior (Throughput) edition:** planning weight is now **conditional on risk**, not uniform; the social rules (fresh-context review, test integrity) get **mechanical enforcement**; the uncorroborated external "68%" stat is **replaced by a metric you measure here**; parallelism was marked **never-yet-exercised in this repo** (the claim when this edition landed in #164; §0 records the runs since); sourcing leans on the primary Anthropic *AI-Native SDLC* course rather than an unverifiable secondary synthesis.

---

## 0. Measure before you theorize

This doc's claims are only as good as the repo's own numbers. Before adding a lane, a gate, or a rule, pull the real data:

- `scripts/dials.sh` — open→green (pipeline health) and green→merge (merge-gate latency), per merge day.
- Review-minutes per PR and the **catch-rate log** (§6) — the real optimization target. Not started yet; begin it before trusting any claim that leans on it.
- Honest baseline as of 2026-11-07 (dates in US Central), recorded here so nobody mistakes aspiration for practice: **parallel lanes have run on two days, and neither is a steady state.** Sprint 6.7's 11 slices shipped *serially*, before `scripts/lane.sh` existed. On 2026-10-30 two worktree lanes ran at once (#212 → PR #215, #213 → PR #216), at Stage 2's WIP = 2. On 2026-11-07 four ran at once (#289, #310 slice 1, #344, #306 → PRs #357–#360), past WIP = 2 by explicit choice. Later that day #362, #363 and #365 (PRs #366, #369, #370) ran alongside #361 (PR #371). `main`'s Tests workflow stayed green after each of those eight merges, although four of them (#358, #360, #370, #371) merged on bases behind `main` while "require branches to be up to date" was still off. Two days are not the logged week Stage 2's exit asks for (§3), so the multi-lane parts of §4 are design intent tried twice, not observed steady state.
- On the evening of 2026-11-06, `main` went red twice. Both times, PRs opened on 2026-11-04, from a batch authored concurrently over 2026-11-03/04, merged in a batch on stale bases: #332 vs `tests/test_portal_urls.py` (fixed by #347), and #339 vs #319 (fixed by #351). More PRs in flight put more of them on older bases. "Require branches to be up to date" went back on after #371 merged on 2026-11-07, together with validate-and-ship Step 7.4, which carries a review attestation across a clean merge from `main` (#361, #371).

---

## 1. The spine: one risk classifier drives everything

The single structural idea in this edition. A change's **risk tier** — decided by the paths it touches — sets its planning weight, its protected files, whether it hits the eval gate, and who merges it. This extends the merge-by-class path rule you already run; it does not invent a parallel system, but the high-risk path set below is genuinely new and domain-specific, so it earns real judgment, not a copy-paste.

| Tier | What's in it (ResearchFlow paths) | Planning weight | Merge actor | Eval gate | Golden files |
|---|---|---|---|---|---|
| **High** | PHI boundary — `app/services/sql_validator.py` (`SQLValidator`, aggregate-only gate); cohort & phenotype semantics — `app/services/sql_synthesis.py`, `app/agents/phenotype_agent.py`, `app/services/feasibility_service.py`, `app/agents/extraction_agent.py`; auth / RBAC / audit — `app/security/**`; encryption; IRB-scope logic; the golden fixtures themselves | Full `grill-with-docs` → design doc → ADR | **Human**, always | **Required if LLM-touching** (§5); otherwise rigor comes from the grill→design→ADR chain + always-human merge + locked goldens | Locked (by rule today; the CI diff check in §7 is not built) |
| **Medium** | Behavior changes *outside* high-risk paths — portal UI (non-SQL), non-PHI API endpoints, runner plumbing (`app/sql_on_fhir/runner/**`), orchestration wiring, dev scripts | 5–10 line **intent block in the PR body** (what / why / constraints / non-goals) | Human | If LLM-touching (§5), else no | n/a |
| **Low** | docs-only; test-only (non-golden); pure refactors with no behavior change outside high-risk paths; harness-internal (`.claude/**`, `scripts/lane.sh`, `scripts/dials.sh`, `docs/DAILY_DEV_WORKFLOW.md`, `CLAUDE.md`) | The issue body **is** the intent — no extra artifact | **Self-merge only for docs-only** (`docs:` title prefix AND only `docs/**` or root-level `*.md`) **and harness-internal** paths — `Merged-By` trailer, SHA-bound attestation. **Human** for test-only and refactors (any `app/**` or `tests/**` path is behavior-touching) and for any PR that changes the merge policy itself (self-amendment carve-out) | no | n/a |

Planning weight and merge actor are separate axes: a test-only change plans like Low but merges like Medium. The canonical merge rule is CLAUDE.md's *Merge actor* section and `/validate-and-ship` Step 8; this table must not diverge from them.

Three consequences this settles:

- **The plan-mode debate dissolves.** "How much to write down" was never one answer. High-risk work earns the full grill→design→ADR chain because a wrong cohort definition or PHI-boundary assumption is expensive and auditable — the 2026 plan-mode discourse's "let the model make reasonable assumptions" posture (Nadeem) is exactly what you refuse *here*, while the course itself prescribes the opposite for risky work ("Interrogate the plan by asking what the change could break, which step is most risky, and what other options Claude chose not to do."). Low-risk work gets nothing but the issue body, because a persisted artifact there only drifts. Medium risk gets the course's `intent.md` content *inlined in the PR* so there's no new file to go stale.
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

The one playbook practice this substrate would otherwise drop — checking the eventual diff against the committed plan — is restored as a review step, not a file (§5).

---

## 2. The evergreen core (proven; unchanged)

These two moves are the win, and Sprint 6.7 proved them — serially, no parallelism required:

1. **Validation is one autonomous pipeline** (`/validate-and-ship`, §5), not a hand-run `/qa` + `/review` + `/ship` chain.
2. **Merging is continuous** — one branch per issue, one PR per issue, merged the moment it's green by the tier's merge actor. The sprint is a planning + retro cadence, not a merge gate.

The binding constraint on everything else is **how many review streams one person can sustain**, and it is **model-independent**: faster models produce more to review, not more attention to review it with. (Anthropic *AI-Native SDLC* course: *"The practical ceiling is how many streams one person can review properly, so add sessions only while review is keeping up."*)

---

## 3. The ramp (parallelism is optional and, here, unproven)

**Stage 1 is done** (pipeline + continuous merge, proven across 6.7). **Stage 0 is partial:** the risk classifier is new in this edition, and the golden-file lock (§7) and eval gate (§5) are not built yet. **Stages 2–3 are trigger-gated: Stage 2 has been tried, not held, and Stage 3 has not been entered.** Parallel lanes have run on two days (§0): two at once on 2026-10-30, and four on 2026-11-07, past Stage 2's WIP = 2 by explicit choice. Neither is a logged week, so Stage 2's exit is unmet; the 2026-11-07 run used Stage 3's lane count without that exit — do not climb for its own sake. **The cap is now 4 under a recorded override (2026-11-07, below the stages), with conditions.**

**Stage 0 — Foundations.** Voice input (§8), the risk classifier (§1), memory write-back (§5.1), evidence-PR template (§6), skill vetting (§9). CI runs real tests on every PR.

**Stage 1 — The pipeline.** `/validate-and-ship` end to end; per-issue branches; continuous merge. *Exit:* three consecutive issues where your only post-handoff involvement was escalated decisions.

**Stage 2 — Two lanes (only when the trigger fires).** *Trigger:* a lane is mid-run on a long autonomous task **and** a second independent, well-specified issue is ready **and** review is keeping up. If any clause is false, a second lane is negative throughput (§10). *Substrate, lightest first:* native `claude --worktree <name>` → `scripts/lane.sh` (WIP guard + dep-sync) → raw `git worktree`. WIP = 2 (4 under the override below). *Exit:* one logged week where no PR waited on you > 1 day.

**Stage 3 — Scale.** 3–5 lanes; native worktrees + background/cloud agents before any external pool tool. No external worktree-pool or "overnight" binary unless it clears §9. *Exit:* none — cruising altitude, only while §10 holds.

**Override, 2026-11-07: up to 4 lanes before Stage 2's exit is met.** This is your decision, recorded as a deliberate override: ADR 0000's pattern of setting a pre-commitment aside on purpose and writing it down. It accepts the review-bandwidth risk Stage 2's exit guards against. That exit is unmet. In the week to 2026-11-07, all 16 merged PRs numbered #317–#338 waited 58–72 h on you, measured as defined below. `scripts/dials.sh 70` shows only 14 of them, at 55–64 h, because later pushes restarted its clock on the other two.

The new information lowers collision risk and re-review churn, not review load:
- "Require branches to be up to date" is back on, so PRs can no longer merge on stale bases. Stale bases caused both 2026-11-06 red-main incidents (§0).
- Validate-and-ship Step 7.4 carries a review attestation across an update from `main` when three things hold: the update is a merge, the root verdict is `SHIP`, and `main` changed none of the PR's files. Any other update still needs a fresh review.

Review load is what the rules below bound.

*Waiting on you* runs from a PR's first attestation comment with a `SHIP` or `SHIP-WITH-FIXES` verdict until it merges, or until now if it's still open. dials.sh's green→merge can't measure it: its clock restarts whenever a branch is updated from `main`, which strict protection makes routine. For example, #294 shows open→green 608m and green→merge 0m.

Before opening a lane, all of these must hold:
- Fewer than 2 PRs await your decision (§10, unchanged).
- No open PR has waited on you more than 24 h. That's the same bar as Stage 2's exit, and §10 uses the same number.
- Fewer than 4 lanes are open. Count every worktree other than the main checkout whose PR isn't merged or closed, including a lane opened so recently it has no commits yet, and every cloud session. `scripts/lane.sh` refuses a fifth `feat/<n>-` or `fix/<n>-` worktree, but it doesn't see other branch names or cloud sessions.
- The new lane wouldn't be a second High-tier lane.
- Once more than two lanes are open, every lane beyond the second is Low or Medium and shares no planned file with any other open lane.
- Every lane beyond the first meets Stage 2's trigger: a lane is mid-run on a long autonomous task, the new issue is independent and well-specified, and review is keeping up.

Two exceptions:
- **`main` is red or flaky:** drop to one lane, the one fixing it (§10). That lane may open even while ≥ 2 PRs await your decision, or while a PR has waited on you more than 24 h. Under strict protection, a red required check on `main` keeps every PR from merging, so that review debt can't drain and those waits keep growing until `main` is fixed.
- **"Require up to date" is off:** this override's premise is gone. The cap is Stage 2's 2 until you turn it back on.

*Revert to WIP = 2* as soon as any of these happens after this block lands on `main`:
- a PR waits on you more than 24 h before merging;
- a push workflow on `main` fails on a merge commit. A failure doesn't count if it passed on a re-run, or if you attribute it to something outside the merged PRs, such as a new advisory or a runner outage. Write that attribution in the log;
- an escape (§6) traces to a PR merged under this override: a `Revert` of it, an issue it closed reopening, or a bug filed against it.

To revert, open one PR that replaces this block with a dated one-line note and sets `WIP_LIMIT=2` back in `scripts/lane.sh` with its test. It touches `tests/**`, so you merge it.

The log is `docs/audits/lane-cap-override.md`, kept for as long as this override stands. It holds each merged PR's wait (as defined above), main's failed push runs with any attribution, and `scripts/dials.sh` output.

The first 7 days after this block lands are the logged week Stage 2's exit asks for. That week counts only if at least 5 PRs merged in it and you ran 3 or more lanes at once on at least one day; note when in the log. Otherwise, extend it until both are true. If the week passes, Stage 2's exit is met and the cap stays at 4, inside Stage 3's 3–5. Going past 4 is a separate decision.

---

## 4. The daily workflow

### 4.1 Single-lane issue loop (the current, complete mode)

```
branch per issue           → fix/<issue> or feat/<issue>  (branch BEFORE editing)
classify (§1)              → tier sets planning weight + merge actor + gate
plan to tier               → low: none · medium: PR intent block · high: grill→design→ADR
/tdd                       → tests committed BEFORE implementation, then LOCKED (§7)
/diagnose                  → if stuck >20 min; wire-level empirical confirmation first
/validate-and-ship (§5)    → qa → fresh-context review → commit → rebase → PR w/
                             evidence → SHA-bound attestation → CI (+ eval gate when built,
                             if LLM-touching) → merge by tier
merge                      → human, except docs-only / harness-internal low (§1)
write-back                 → any correction this change needed → one dated line in
                             CLAUDE.md before the next issue
```

### 4.2 Multi-lane day shape — tried on two days, not a steady state

> Two runs so far (§0): 2026-10-30 at WIP = 2, and 2026-11-07 at four lanes by explicit choice; no logged week. It runs at up to four lanes under the §3 override of 2026-11-07, and only on that override's conditions. The first qualifying week (§3) is the logged week; until then this is design intent tried twice.

PLAN (fill queue to lanes × 2) → LAUNCH (one agent per lane) → MANAGE (review evidence, answer escalations, merge greens) → WRITE-BACK.

### 4.3 Sprint start = queue-fill cadence

`/grill-with-docs` → design doc (**for high-risk deliverables**) → `/to-issues` → 5–10 vertical slices labeled `ready-for-agent`, **each pre-classified by tier**. Plan quality still buys autonomy — but spend it where blast radius warrants, not uniformly.

### 4.4 Sprint end = quality + learning event

`/improve-codebase-architecture` (entropy pass) → `/qa` (integration-level) → `/retro` (15 min, append ADR). Merging already happened continuously; sprint end verifies the *whole*, not slices.

---

## 5. The composite pipeline — `/validate-and-ship`

One invocation, "code done" → "merged or escalated":

1. `/qa` on the change.
2. **Fresh-context review** — a clean reviewer subagent spawned by `/validate-and-ship`, never the authoring session, posting **one consolidated verdict** (never a comment stream; that spends the §10 bandwidth it's meant to save). Running it as a non-interactive CI check is target state (§7); no workflow in `.github/workflows/` runs it yet. For **high-tier** changes the reviewer also asserts the diff matches the approved design doc / ADR, and that any departure is recorded in this PR — the playbook's plan-vs-reality discipline (check the diff against the committed plan; when it departs, update the plan in the same commit), applied to the ADR instead of a `plan.md`.
3. Apply mechanical fixes; **escalate behavior-changing findings** to the human.
4. Conventional commit on the issue branch; rebase onto latest `main`.
5. Push; open PR with the Testing-Evidence section filled from step 1's real output.
6. Post the **SHA-bound review attestation** (step 2's consolidated verdict + reviewed commit SHA == `headRefOid`).
7. CI runs real tests, including the docker-compose `service-dependent-tests` job and `tests/eval/test_eval_replay.py` on every PR. The **eval gate** (target state, not built: #136/#137/#142 are open) would add a run iff the change is LLM-touching (trigger list below).
8. On green, **merge by tier** (§1). Green means every workflow run for the head SHA has completed and passed, not just the checks visible so far: a `needs:` job has no check until its dependencies finish, which is how #203 merged early. Then: human reads the consolidated verdict and signs for high/medium; docs-only / harness-internal low self-merges under the standing rule with `--match-head-commit`; everything else, and any change to the merge policy itself, is human-merge.

These steps are the workflow-level shape; `.claude/skills/validate-and-ship/SKILL.md` is authoritative for execution and numbers its steps differently.

**LLM-touching trigger for the eval gate** — the surfaces that actually call a model, named correctly (not the retired `query_interpreter.py`):

- `app/services/sql_synthesis.py` (exploratory NL→SQL synthesis — #76 territory),
- `app/agents/requirements_agent.py` (concept extraction),
- `app/utils/llm_client.py` / `app/utils/multi_llm_client.py` and every caller — today `calendar_agent` / `delivery_agent` (via `langgraph_workflow`) and `app/services/conversation_manager.py` (`LLMClient` fallback); re-derive with `git grep -ln 'LLMClient\|MultiLLMClient\|import anthropic' app/` rather than trusting this list,
- any prompt or model-config file.

When built, the gate uses `#136`/`#137`/`#142`'s harnesses, sets **per-domain thresholds**, runs on those paths + nightly, and **asserts it executed N cases** — an eval that passes on zero cases is worse than none (this repo has already had one integration job that was silently a no-op).

**Attestation reconciliation:** the fresh-context reviewer *produces* the verdict; it does not *become* the merge actor. For high/medium a human still reads the consolidated verdict and merges — the attestation records a human sign-off. For docs-only / harness-internal low, the verdict + SHA-bound comment is itself sufficient to self-merge. This keeps the merge-governance the Throughput Edition got right intact.

### 5.1 Delegation + memory (unchanged principles)

Delegate outcomes with the *why*. Never review in the authoring session (enforced by §5 step 2). Escalation split: behavior → human, mechanical → the agent. Don't take back control — teach via a dated CLAUDE.md line. **Lane-close check:** "Did this change need a correction? If yes, one dated rule-line in CLAUDE.md before the next issue."

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

- **Test integrity — protect golden files, not all `tests/**`.** The high-value targets are `tests/fixtures/transpiler_expected_outputs.py` and the eval case sets (`tests/eval/cases.py`, `tests/eval/fixtures/**`). The `logs/sprint_*_gate.jsonl` files are gate *evidence output* and gitignored, so no CI check can see them; protect the inputs, not the logs. "Regenerate expected outputs to match" is exactly how a #76-style silent bug passes. Rule (works under `/tdd`, where the agent writes the tests): **tests are committed before implementation and locked from then until the task ends.** Enforce with the lightest equivalent — a CI diff check on the golden paths over a PreToolUse hook if the CI check suffices.
- **Fresh-context review as a CI check** (§5 step 2) — target state, not built: today the reviewer runs in-session via `/validate-and-ship`.
- **Drift at its source.** Status claims — node counts, test counts, "shipped" markers — are **generated or checked by a script**, never hand-typed into CLAUDE.md / CONTEXT.md / issues. (The Throughput Edition's "23-state vs 17-nodes" and "12 vs 1 integration tests" were status drift, not design-doc drift — lighter planning would not have prevented them; generated counts would.) Design docs and ADRs are stamped **point-in-time** so nobody reads them as current state.

---

## 8. Voice input

You talk faster than you type, and the cost of attaching the *why* drops to near zero. At planning volume this is the difference between thin and deep plans. macOS: OpenSuperWhisper (local Whisper, hotkey) or built-in dictation. Voice for intent/context/plans; keyboard for identifiers, paths, code.

---

## 9. Skill / tool vetting (the "§5.5 bar", unchanged)

*"§5.5" is this bar's legacy section number; the vetting ledger (`docs/audits/vetting-ledger.md`) still cites it by that name.*

Before any skill or executing tool: read the whole `SKILL.md` **and** bundled scripts; grep for network calls, `curl | bash`, credential/env access, package installs; require a named maintainer + pinned version/commit; trial command-runners in a throwaway repo; never install mid-task on an agent's suggestion — finish, then vet cold. **This bar applies to the mechanisms in §7 too** — a test-lock hook or eval-gate script is tooling you must vet and maintain, not free safety.

---

## 10. Throughput guardrails

- **Verified merges per week** (defined in §6) — the only merge count that matters.
- **Cycle time:** plan-handoff → merge; `dials.sh` computes only its open→green and green→merge sub-intervals. Ballooning means thin plans or over-escalation — fix before adding lanes.
- **WIP = review streams you can actually unblock.** Model-independent ceiling. The cap is 4 under the §3 override of 2026-11-07 and its conditions, and 2 if that override is reverted. `scripts/lane.sh` refuses a fifth `feat`/`fix`-numbered worktree; count other lanes yourself. Scale to N+1 only when escalations-per-lane are low and nothing waits on you > 24 h (§3), except the fix lane (§3).
- **Review-debt rule:** no new lane while ≥ 2 PRs await your decision, except the one lane fixing a red `main` (§3).
- **Never scale past validation:** pipeline red/flaky → one lane until green.
- **Queue health:** refill to lanes × 2; starvation means the plan block was thin.
- **The memory loop is the ceiling-raiser:** write-backs, ADRs, retros, generated status — the compounding practices are what make month three faster than month one.

---

## 11. Not adopted — and the honest cons

- **Editor/terminal migration (Neovim/WezTerm):** downstream of muscle memory, not the source of speed. Skip.
- **Production Maintain loop (playbook Stage 6: Maintenance):** there is **no production deployment yet**, so the prod-anomaly→replan loop doesn't apply literally. The version that *does*: post-merge signals you already have — CI failures on `main`, eval regressions, cost/drift telemetry (#151), LangSmith traces — **auto-file issues into the queue**. Build that, not the prod loop.
- **The planning stance is a position, not a law.** The 2026 plan-mode discourse (Nadeem's "plan mode is dead"; instil's "spec-driven dead, long live plan mode") is ~a handful of posts over a month, mostly about general work where output is cheap to check — not a consensus, and not obviously transferable to PHI/cohort work. This edition's risk tiering is the hedge: it refuses heavy artifacts where they'd only drift (low/medium) and keeps them where blast radius is real (high). If your measured catch-rate (§6) ever shows high-tier grilling isn't catching more than medium-tier intent blocks, revisit this.

---

## 12. Cheat sheet

| Moment | Chain | Rule |
|---|---|---|
| New issue | classify (§1) → plan to tier | low: none · medium: PR intent block · high: grill→design→ADR |
| Build | `/tdd` → **/validate-and-ship** | tests committed + locked before impl (§7) |
| Stuck > 20 min | `/diagnose` | wire-level empirical confirmation first |
| PR | evidence template (§6) + SHA-bound attestation | tier sets merge actor |
| Merge | by tier | human, except docs-only / harness-internal self-merge (`--match-head-commit`) |
| LLM-touching change | eval gate (§5) | per-domain thresholds; assert N cases ran |
| Lane close | memory write-back if corrected | one dated CLAUDE.md line |
| Sprint end | `/improve-codebase-architecture` → `/qa` → `/retro` | ADR appended, point-in-time stamped |
| New skill/mechanism | §9 vetting | read everything; pin; never mid-task |
| Scaling check | §10 | escalations low + no review debt + CI green |

---

*Sourcing note:* practices corroborated primarily by Anthropic's *AI-Native SDLC Playbook* (claude.com/resources/articles/the-ai-native-sdlc-playbook; quotes checked verbatim 2026-10-20) and triangulated against the 2026 plan-mode discourse. No load-bearing claim rests on an unverifiable secondary source; the one quantitative claim (§6) is measured in this repo, not imported.
