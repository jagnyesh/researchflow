# Daily Agentic Development Workflow — Throughput Edition

**Recast for:** everyday coding, optimized for raw throughput — verified changes merged per week.
**Synthesis of:** the existing Pocock/gstack three-scale loop × Kun Chen's agentic engineering method (ex-L8 Meta/Microsoft/Atlassian, led Rovo Dev).
**Applies to:** ResearchFlow and any future repo. Suggested home: commit as `docs/WORKFLOW.md` so agents can read it too.
**Source for Kun's method:** his ByteByteGo guest post and YouTube walkthrough (June 2026). All descriptions paraphrased.

---

## 1. Verdict up front

Your foundation is already sound. It matches Kun's on agent onboarding, planning discipline, and validation philosophy — his "force end-to-end evidence, never trust green unit tests alone" principle is the same lesson you extracted from the langchain-anthropic silent-transmission bug and the aggregator double-charge bug. The foundation doesn't change. What changes is the shape built on top of it.

Converting that foundation into raw throughput takes three structural moves:

1. **Validation becomes one autonomous pipeline, not a hand-run chain.** Today /qa, /review, and /ship are separate manual invocations. Kun's throughput exists because `no-mistakes` runs the whole validate→rebase→review→test→PR→CI sequence without him. You need the equivalent (§5.8) before anything else scales.
2. **Work runs in parallel lanes.** Worktrees + tmux windows, each lane an agent pulling from a planned queue (§5.6, §5.7).
3. **Merging goes continuous.** The old model — commits accumulate on a feature branch, one PR at sprint end — dies here. Parallel lanes can't share a branch anyway. New model: **one branch per issue, one PR per issue, merged the moment it's green.** The sprint survives as a planning and retro cadence, not a merge gate. This is the single biggest rewiring of your current git flow; §4.2–4.4 spell it out.

One sequencing warning, and it's engineering logic, not caution for its own sake: **pipeline before parallelism.** Kun runs 5–10 lanes only because his pipeline autonomously reviews, produces E2E evidence, and babysits CI — his own telemetry caught bugs in 68% of agent changes before they reached him. Parallel lanes without that net just merge bugs faster. The ramp in §3 sequences the build-out so each stage earns the next.

---

## 2. Pillar-by-pillar comparison

| Pillar | Kun's implementation | Your current system | Verdict |
|---|---|---|---|
| **Environment** | WezTerm + tmux + Neovim, fully keyboard-driven; agent-agnostic harnesses | Claude Code in terminal; existing editor | Keep your editor. **tmux is now core, not optional** — lanes live in tmux windows (§5.6). |
| **Agent onboarding** | CLAUDE.md/AGENTS.md memory files; teach the agent by writing corrections into memory; hard warning against unvetted skills | CLAUDE.md with @-imported living docs, skill-routing table, operating-discipline section with documented precedents | At or above parity. Formalize the write-back trigger (§5.3) and the vetting checklist (§5.5). At multiple lanes, memory quality is what keeps every lane aligned. |
| **Ergonomics** | Voice input (OpenSuperWhisper, local Whisper, hotkey); outcome-based delegation; never take back control | Typed prompts; /grill-me | **Adopt voice (§5.1).** At queue-planning volume, dictation is the difference between thin plans and deep ones. |
| **Planning** | Lavish Editor interactive plan artifacts; plan quality determines how long the agent runs autonomously | /grill-with-docs → design doc → /plan-eng-review → /to-issues | Functional parity — and now **the throughput lever**. Autonomy duration per lane is set entirely by plan depth. Batch-plan to keep the queue ahead of the lanes (§4.3). |
| **Validation** | `no-mistakes`: conventional commit, rebase, fresh-context peer review, forced E2E evidence, docs/lint, PR, CI babysit — fully autonomous, escalates only ambiguity | /qa + /review + /ship as separate manual steps; pre-commit hooks; security CI; test CI landing via issue #25 | **Build the composite pipeline (§5.8).** #25 PR-A graduates from "planned" to **the critical path** — it's the CI leg of your pipeline. |
| **Parallelism** | `treehouse` manages a pool of pre-warmed worktrees; 5–10 tasks in tmux windows with agent status in tab titles | Serial, single session | **Adopt via the ramp (§3, §5.7).** Plain `git worktree` at two lanes; treehouse when lane churn is daily. |
| **Long-running tasks** | `gnhf` ("good night, have fun"): decomposes a huge task, fresh context per step seeded with prior learnings, auto-rollback, token budget, leaves branch + notes.md | None | **Adopt the pattern for bulk work (§5.9).** Overnight hours are free throughput. |
| **Remote control** | Tailscale + SSH + mosh + tmux attach from phone | None | Optional, later. Becomes genuinely useful at 3+ lanes, when an away-from-desk block stalls real work (§6). |

---

## 3. The ramp

Each stage has an exit criterion. Don't skip stages — every one exists to keep the next from multiplying unverified output.

**Stage 0 — Foundations (this week, ~2 hours setup + in-flight work)**
- Voice input (§5.1), fresh-context review rule (§5.2), memory write-back (§5.3), evidence-PR template (§5.4), vetting checklist (§5.5), tmux basics (§5.6).
- Push #25 PR-A (docker-compose test CI) to green. This is now the critical path, not background work.
- *Exit criterion:* CI runs real tests on every PR; you've run one full issue through the loop with a fresh-context review.

**Stage 1 — The pipeline (next 1–2 sprints)**
- Build the composite `/validate-and-ship` chain (§5.8): one invocation from "code done" to "PR open with evidence, CI watched, ambiguity escalated."
- Switch to per-issue branches and continuous merge (§4.2).
- *Exit criterion:* three consecutive issues merged where your only involvement after handoff was decisions the pipeline escalated.

**Stage 2 — Two lanes**
- Second lane via plain `git worktree` (§5.7), second tmux window, agent status visible in window names. WIP limit: 2.
- *Exit criterion:* a week at two lanes where escalations stayed manageable and no PR sat waiting on you for more than a day.

**Stage 3 — Scale**
- 3–5 lanes; adopt treehouse once worktree churn is daily and the manual setup friction (deps, .env, sync) is what you feel.
- Overnight gnhf-style runs for bulk, evaluator-scored tasks (§5.9).
- *Exit criterion:* none — this is cruising altitude. Scale lanes only while §7's guardrails hold.

---

## 4. The daily workflow

### 4.0 Day shape (throughput mode)

```
Block 1 — PLAN (60–90 min, first)
  Grill and refine plans; convert BACKLOG items into ready-for-agent
  issues. Plan depth here sets autonomy duration everywhere else.
  Target queue depth: lanes × 2.

Block 2 — LAUNCH
  One agent per lane. Each lane: pick issue → hand off the plan →
  agent runs. You leave.

Block 3 — MANAGE (rest of day, interrupt-driven)
  Watch lane statuses. Answer escalations. Review evidence, not
  diffs. Merge green PRs. Relaunch idle lanes from the queue.

Day end — WRITE-BACK (§4.6)
  Memory updates, CONTEXT.md, optionally queue an overnight task.
```

The identity shift this encodes, in Kun's framing: you stop being the engineer on one task and become the manager of a small always-on team. Your job is plans in, decisions back, merges out.

### 4.1 Session start ritual (≤5 min)

```bash
tmux attach -t researchflow || tmux new -s researchflow
git status && git pull
```

1. Skim `CONTEXT.md` — confirm queue state and any overnight results.
2. Launch Claude Code per lane. CLAUDE.md auto-loads the living docs.
3. Resuming a lane mid-issue: `/context-restore`.
4. Dictate lane objectives by voice — outcome + why, not a step list.

### 4.2 The issue loop (Scale 1 — one lane, one issue)

```
git worktree / checkout    → new branch per issue: fix/<issue> or feat/<issue>
/grill-me                  → align on outcome (skip only if the plan from
                             Block 1 is already crisp)
/tdd                       → red, green, refactor
/diagnose                  → if stuck >20 min; wire-level empirical
                             confirmation BEFORE scoping fixes (keep this rule)
/validate-and-ship (§5.8)  → the pipeline takes it from here:
                             /qa → fresh-context review → conventional commit
                             → rebase onto main → push → PR with Testing
                             Evidence → watch CI → escalate ambiguity only
merge on green             → squash-merge, delete branch
memory write-back          → any correction this lane needed → one dated
                             line in CLAUDE.md before the lane relaunches
```

**What changed from the old flow:** no more parking commits on a shared feature branch until sprint end. Every issue is its own branch and its own PR, merged the moment the pipeline and CI say green. Small PRs merge faster, conflict less, and are the only model that works once lanes run in parallel.

### 4.3 Sprint start → becomes the queue-fill cadence

```
/grill-with-docs   → align on the sprint's deliverable, write/refresh design doc
/to-issues         → break into 5–10 vertical slices, labeled ready-for-agent
```

Same skills as before, new job: the sprint plan is now a **queue** the lanes drain continuously, not a batch that ships at once. Mantra stands: plan quality = autonomy duration. A one-line prompt buys minutes of lane autonomy; a grilled design doc buys hours. Refill mid-sprint in Block 1 whenever queue depth drops below lanes × 2.

### 4.4 Sprint end (Scale 2 — lighter now)

```
/improve-codebase-architecture   → entropy pass across everything merged
/qa                              → full end-to-end sweep of the integrated system
/retro (15 min)                  → what worked, what to change; append the
                                   sprint ADR to DECISIONS.md
```

Merging already happened continuously, so sprint end stops being a shipping event and becomes a **quality-and-learning event**: integration-level QA (per-issue pipelines verify slices; this verifies the whole), entropy cleanup, and the retro that tunes the next sprint's plans. /retro matters more at throughput, not less — it's where you find which plan patterns bought the longest autonomy.

### 4.5 Release (Scale 3 — unchanged)

```bash
git checkout main && git pull
git tag -a v1.0 -m "v1.0 — <milestone>"
git push origin v1.0
gh release create v1.0 --notes-file RELEASE_NOTES.md
```

### 4.6 Day end ritual (≤10 min)

1. Update `CONTEXT.md` — queue state, lane states, overnight expectations.
2. Memory write-back for any lane corrections not yet captured.
3. If a bulk task qualifies (§5.9), queue the overnight run with a token budget.
4. Detach tmux. Lanes with running pipelines keep going.

---

## 5. Practices in detail

### 5.1 Voice input

Why: you talk several times faster than you type, and the cost of including context ("here's *why* I want this") drops to near zero. At throughput, your main output is plans and lane instructions — pure dictation territory. Kun wrote his entire post mostly by voice.

Setup:
- **macOS:** OpenSuperWhisper (free, open source, runs Whisper large-v3-turbo locally, global hotkey). Alternatives: MacWhisper, superwhisper. Zero-install trial: built-in macOS dictation.
- **Windows:** trial with built-in voice typing (`Win+H`); for local Whisper, any whisper.cpp frontend.
- **Usage pattern:** voice for intent, context, plans, and lane objectives. Keyboard for identifiers, paths, and precise edits. Don't dictate code.

### 5.2 Delegation and the fresh-context review rule

Four principles, written into CLAUDE.md so every lane inherits them:

1. **Delegate outcomes, not actions, with the why attached.** Not "rename this variable" but "audit this module's naming against `.claude/architecture.rules` — we're standardizing before the next integration pass." The why lets the agent generalize and run longer without you.
2. **Never review in the authoring session.** The session that wrote the code assumes its own intent — it's checking its own homework. Reviews run in a fresh context (the pipeline enforces this, §5.8). Highest-leverage line in Kun's whole validation stack.
3. **Escalation split:** findings that would change product behavior come to you; mechanical findings (lint, naming, dead code) the agent fixes itself. At multiple lanes this split is what keeps you off the critical path.
4. **Don't take back control — teach.** When a lane errs, the reflex is feedback plus a memory write-back (§5.3), not "I'll do it myself." Taking over makes you the bottleneck across every lane at once.

### 5.3 Memory write-back (the compounding habit)

You already run the heavyweight version — the operating-discipline section in CLAUDE.md with documented precedents. Make the trigger mechanical:

> **Lane-close check:** "Did this lane do anything I had to correct? If yes: append one dated line to CLAUDE.md (or architecture.rules) stating the rule, with today's case as precedent — before the lane relaunches."

Two minutes, compounds forever, and at multiple lanes it compounds *multiplicatively*: a correction captured once fixes every future lane. Skipping it means re-teaching the same lesson in parallel.

### 5.4 Evidence-bearing PRs

At throughput you stop reading diffs line-by-line — Kun is explicit that he rarely does. What you review instead is **evidence**. Every PR the pipeline opens carries:

```markdown
## Testing evidence
- Commands run: `pytest tests/... -x` → 42 passed, 0 failed
- E2E exercised: <what was driven, expected vs. observed>
- Artifacts: <screenshot / output paste / LangSmith trace link>
- Not covered: <gaps and why they're acceptable>
```

This is also the audit trail your domain habits already favor: every merged change carries its own proof-of-function, reviewable after the fact. Green unit tests alone don't clear the bar — your two wire-level bugs are the standing reason why.

### 5.5 Skill vetting checklist

Kun's sharpest warning: unvetted skills are a supply-chain and prompt-injection surface, and bloated skills silently degrade agent performance — a cost you now pay per lane. Before installing any skill:

1. Read the entire SKILL.md **and any bundled scripts** — not the README.
2. Grep for network calls, `curl | bash`, credential/env access, and package installs.
3. Named maintainer, public repo, pin the version or commit.
4. If it executes commands, trial it in a throwaway repo first.
5. Re-review on every update; prune skills unused for a month (each one is context cost + attack surface in every lane).
6. Never install a skill mid-task because an agent suggested it. Finish the task, vet it cold.

Your current sources (gstack, Pocock) pass because you can name the maintainers and read the code. Keep that bar as you add tools like treehouse and gnhf — vet those the same way.

### 5.6 tmux — now core

Lanes live here. Session persistence means running pipelines survive a closed terminal; window names are your lane dashboard.

```bash
brew install tmux                     # or apt install tmux
tmux new -s researchflow              # named session
# Ctrl-b c        → new window (= new lane)
# Ctrl-b ,        → rename window:  lane1:#82-running / lane2:NEEDS-INPUT
# Ctrl-b n / p    → cycle lanes
# Ctrl-b d        → detach; everything keeps running
tmux attach -t researchflow           # reattach
```

Claude Code surfaces status in titles out of the box; keep window names carrying issue + state so one glance tells you which lane needs you. That visibility trick is, per Kun, what makes many lanes manageable without losing your mind. Skip the config-file rabbit hole; defaults are fine.

### 5.7 Worktree lanes

A worktree is a second checkout of the same repo in another directory — parallel agents without stepping on each other.

```bash
# open a lane
git worktree add ../rf-issue82 -b fix/issue-82
cd ../rf-issue82
cp ../researchflow/.env .             # env doesn't follow automatically
uv pip sync config/requirements.lock  # deps don't either

# housekeeping
git worktree list
git worktree remove ../rf-issue82     # after the PR merges
```

That setup friction (env, deps, sync-to-main, reuse) is exactly what Kun's `treehouse` automates with a pool of pre-warmed worktrees. Adopt it at Stage 3, when you're opening lanes daily and the manual steps are what you feel. Until then, plain `git worktree` is fine at two lanes.

### 5.8 The composite pipeline — your `no-mistakes`

The single highest-leverage build in this document. One invocation — call it `/validate-and-ship` — that chains what you currently run by hand:

1. `/qa` on the change
2. **Fresh-context review**: spawn a clean reviewer session/subagent on the diff (this is the one legitimate early use of subagents your backlog deferred — a single reviewer in a fresh context, nothing more)
3. Apply mechanical fixes; **escalate** behavior-changing findings to you
4. Conventional commit on the issue branch, rebase onto latest main
5. Push, open PR with the Testing Evidence section filled from step 1's actual output
6. Watch CI; report green or escalate red

Write it once as a skill — you already have the skill-distillation work backlogged (doc-reorg Phase 3), and this becomes its first entry. #25 PR-A is the CI leg; without real tests in CI, step 6 is theater. Kun's stat is the justification for the effort: two-thirds of agent changes carried bugs his pipeline caught before he saw them. Yours will too.

### 5.9 Overnight bulk runs (the gnhf pattern)

For tasks too big for one context window or too mechanical to babysit: decompose into steps, run each in a **fresh context** seeded with a shared base plus accumulated learnings (a notes.md), auto-rollback failed steps, cap the token budget, wake up to a branch with organized commits and a summary.

Use Kun's open-source `gnhf` (vet it per §5.5) or approximate the loop with your own harness. It fits three shapes of work:

- **Implement a large, fully-grilled plan** end to end.
- **Drive a measurable metric** — test coverage up, LOC down, startup latency down — with functionality pinned by the test suite.
- **Evaluator-scored experiments** — anything where a script can grade each attempt.

Your ready-made first case: regenerating transpiler expected-outputs against fresh Synthea data — mechanical, verifiable, and already on your radar as recurring work. Overnight hours are free throughput; this is how you collect them.

---

## 6. Not adopted — and what would change the answer

**Editor/terminal migration (Neovim, WezTerm).** Kun's setup rides on ~30 years of terminal muscle memory; the tools are downstream of that, not the source of the speed. Migrating costs weeks of throughput to gain keyboard purity you can approximate with your current editor's shortcuts. Revisit only if genuine curiosity outlives a slow month.

**Lavish Editor.** Your grill chain already produces deep, adversarially-reviewed plans; the interactive-HTML rendering is a nicer surface, not a deeper plan. Try it out of curiosity; adopt only if annotate-in-browser measurably beats markdown iteration for you.

**Remote control (Tailscale + SSH + mosh).** Adopt at Stage 3 if lanes regularly stall waiting on decisions while you're away from the desk. At 1–2 lanes, escalations can wait until you're back.

---

## 7. Throughput guardrails

Raw throughput that merges regressions is negative throughput. These keep the number honest:

- **The metric: verified merges per week.** Verified = evidence section + green CI + fresh-context review. Unverified merges don't count; they're inventory of future rework.
- **Cycle time is the second dial:** plan-handoff → merge, per issue. If it balloons, plans are too thin or the pipeline is escalating too much — fix those before adding lanes.
- **WIP limit = lanes you can actually unblock.** Scale to N+1 only when escalations-per-lane are low and nothing waits on you overnight.
- **Review-debt rule:** no new lane launches while ≥2 PRs sit awaiting your decision. Draining beats queueing.
- **Never scale past validation.** Pipeline red or flaky → drop to one lane until it's green again. Kun's 68% catch rate is the standing argument: that's the volume of bugs that reaches main the moment the net is down.
- **Queue health:** refill in Block 1 to lanes × 2. Starving lanes means the plan block was too thin — the fix is planning depth, never skipping the grill.
- **The memory loop is the ceiling-raiser.** Write-backs, ADRs, retros, conventional commits — the compounding practices are what make month three faster than month one. Throughput without them plateaus at whatever the agents can do unteached.

---

## 8. Compressed cheat sheet

| Moment | Chain | Commands / rules |
|---|---|---|
| Day start | PLAN block first: grill + fill queue to lanes × 2 | Voice-dictate plans; /grill-with-docs, /to-issues |
| Launch a lane | worktree → branch → hand off plan | `git worktree add ../rf-<issue> -b fix/<issue>`; copy .env, sync deps |
| Issue (per lane) | /grill-me → /tdd → **/validate-and-ship** | Pipeline: qa → fresh review → commit → rebase → PR + evidence → CI |
| Stuck >20 min | /diagnose | Wire-level empirical confirmation before scoping fixes |
| PR green | Squash-merge, delete branch, relaunch lane | Review evidence, not diffs; merge continuously |
| Lane close | Memory write-back if corrected | One dated line in CLAUDE.md before relaunch |
| Sprint start | /grill-with-docs → /to-issues | Queue-fill cadence; plan depth = autonomy duration |
| Sprint end | /improve-codebase-architecture → /qa (integration) → **/retro** | ADR appended; find which plan patterns bought the longest autonomy |
| Release | tag | `git tag -a`, `gh release create` |
| Overnight | gnhf-pattern bulk run | Budget-capped; evaluator-scored or plan-driven only |
| New skill/tool | Vetting checklist (§5.5) | Read everything; pin versions; never mid-task |
| Scaling check | §7 guardrails | Escalations low + no review debt + CI green → add a lane |
