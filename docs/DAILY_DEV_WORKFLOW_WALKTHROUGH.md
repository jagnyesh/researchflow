# DAILY_DEV_WORKFLOW — Step-by-Step Walkthrough

A reading guide to `DAILY_DEV_WORKFLOW.md`. It explains, section by section, **what each part says, why it's there, and how to use it** — with concrete ResearchFlow examples. Companion doc; the workflow doc itself is the source of truth.

---

## The one idea, in a sentence

**A change's risk decides how much ceremony it gets.** Everything else in v2 — how much you plan, which files are locked, whether an eval runs, who clicks merge — falls out of that one classification. If you remember nothing else, remember: *classify first, then the workflow tells you what to do.*

## Why v2 exists (the problem it fixes)

v1 applied the **same heavy process to every change** and justified that with "plan depth = autonomy duration." Two things were wrong with that:

1. A one-line README fix got reasoned about as if it were a change to PHI-boundary logic. Wasteful, and the extra artifacts drift.
2. The sharpest rules ("never review your own code," "don't weaken a test to make it pass") were **honor-system** — nothing enforced them.

v2 keeps v1's proven core (the auto pipeline + continuous merge) and fixes those two: **planning is proportional to risk**, and **the honor-system rules become machine-enforced**.

---

## Walkthrough, section by section

### §0 — Measure before you theorize

**What it says:** before adding any lane, gate, or rule, look at the repo's real numbers (`scripts/dials.sh`, review-minutes, the catch-rate log). And it records an honest baseline: *parallel lanes have never actually run here.*

**Why:** the whole analysis chain that produced v2 caught itself theorizing about parallelism the repo has never used. This section is a guard against that — don't design for a reality you haven't measured.

**How to use it:** when tempted to add machinery, run `dials.sh` first and ask "does the data say I need this?"

### §1 — The spine: one risk classifier

**What it says:** every change is **Low / Medium / High** risk based on the paths it touches, and the tier sets four things at once — planning weight, protected files, whether the eval gate runs, and who merges.

| If the change touches… | Tier |
|---|---|
| docs, non-golden tests, pure refactors, harness files | **Low** |
| behavior outside the sensitive paths (portal UI, non-PHI endpoints, runner plumbing, scripts) | **Medium** |
| PHI boundary (`sql_validator.py` / `SQLValidator`), cohort & phenotype logic (`sql_synthesis.py`, `phenotype_agent.py`, `feasibility_service.py`, `extraction_agent.py`), `app/security/**`, encryption, IRB scope, golden fixtures | **High** |

**Why:** it's the answer to the "plan mode is dead / long live plan mode" debate. The debate had no single answer because the right amount of planning depends on blast radius. A wrong cohort definition is expensive and auditable; a typo is not. So High gets the full `grill → design doc → ADR` chain; Low gets nothing but the issue text; Medium gets a short intent block written **into the PR** (so there's no separate file to go stale).

**Why it matters that it reuses an existing idea:** you already merge by class (docs self-merge vs behavior-touching → human). The risk tiers extend that same path-based thinking — but note the High path list is genuinely new and ResearchFlow-specific, so defining it is real judgment, not copy-paste.

**One catch:** planning weight and merge actor are separate. Only docs-only and harness-internal Low changes self-merge; non-golden tests and refactors plan like Low but still get a human merge, and so does any PR that changes the merge policy itself.

**How to use it:** first question on any issue — "which paths does this touch?" → tier → the rest of the doc is now decided for you.

### §2 — The evergreen core (unchanged, proven)

**What it says:** two things from v1 survive untouched because Sprint 6.7 proved them: (1) validation is one autonomous command (`/validate-and-ship`), and (2) merging is continuous (one branch/PR per issue, merged when green). The real ceiling on throughput is **how many review streams one human can sustain** — and faster models don't raise that ceiling, they push harder against it.

**Why:** these are the parts that already work. v2 changes the shape *around* them, not them.

### §3 — The ramp (and the honesty label)

**What it says:** Stages 0–1 (pipeline + continuous merge) are **done**. Stages 2–3 (parallel lanes) are **optional, trigger-gated, and have never fired here.**

**Why:** earlier analysis over-weighted parallelism. This section demotes it and labels it plainly so nobody reads §4's multi-lane shape as current practice.

**How to use it:** don't add a second lane until the Stage-2 trigger is literally true — *a lane is mid-run on a long task AND a second ready issue exists AND review is keeping up.* Any clause false → a second lane makes things worse, not better.

### §4 — The daily workflow

**§4.1 is your actual mode today:** branch → **classify** → plan to the tier → `/tdd` (tests committed and then locked) → `/validate-and-ship` → merge by tier → memory write-back. Notice classify is step two — it gates everything after.

**§4.2 is marked ASPIRATIONAL** — the multi-lane "manager of a team" day. It's design intent, not your workflow, until §3's trigger fires.

**§4.3 / §4.4:** sprint start fills a queue of pre-classified issues; sprint end is a *quality + learning* event (integration QA + retro), since shipping already happened continuously.

### §5 — The composite pipeline (`/validate-and-ship`)

**What it says:** one command runs qa → **fresh-context review** (a clean subagent today; a CI check is the target) → commit → rebase → PR with evidence → SHA-bound attestation → CI (plus the **eval gate** for LLM-touching changes, once it's built) → merge by tier.

**Two things to understand here:**

- **The eval-gate trigger is path-specific.** The gate itself is target state (#136/#137/#142 are open). Once built, it fires only for files that actually call a model: `sql_synthesis.py` (exploratory NL→SQL), `requirements_agent.py`, `llm_client.py`/`multi_llm_client.py` and their callers (`calendar_agent`/`delivery_agent` via `langgraph_workflow`, `conversation_manager.py`), and any prompt/model-config file. It will use the #136/#137/#142 harnesses, set per-domain thresholds, and **assert it actually ran N cases** — because a gate that silently passes on zero cases is worse than no gate.
- **The reviewer feeds the attestation; it doesn't replace the human.** For High/Medium, a human still reads the one consolidated verdict and merges. For docs-only / harness-internal Low, that verdict + the SHA comment is enough to self-merge. This keeps the merge-governance intact.

**How to use it:** after `/tdd`, you run one command. Your only job afterward is the decisions it escalates.

### §6 — The metric is yours, measured

**What it says:** v1's borrowed "68% of agent changes had bugs" stat is deleted. Instead you measure the same thing **here**: tag what review catches, track escapes (reverts, reopened issues, bugs against recent PRs), and log review-minutes per PR.

**Why:** the one number the whole doc leans on shouldn't be an unverifiable figure from an outside blog. Your own catch-rate + reviewer-hours is both trustworthy and the actual thing to optimize.

**How to use it:** fill the evidence template on every PR (it now includes the risk tier and the eval scores). Over time the catch-rate log *is* your justification for the WIP limit.

### §7 — Mechanical enforcement (and its price)

**What it says:** turn the honor-system rules into machinery — but **every mechanism has a cost**, so use the lightest one that works and make each gate prove it ran.

- **Test integrity = lock the *golden files*, not all tests.** The dangerous ones are `tests/fixtures/transpiler_expected_outputs.py` and the eval case sets in `tests/eval/` (not the `logs/sprint_*_gate.jsonl` files: those are gitignored run outputs CI can't see). "Regenerate the expected output to match" is exactly how a silent bug (the #76 class) sneaks through. Rule: tests are committed **before** implementation and **locked** until the task ends (this works even under `/tdd`, where the agent writes the tests).
- **Fresh-context review as a CI check** with one consolidated verdict: target state, not built yet.
- **Drift at its source:** status claims (node counts, test counts, "shipped" markers) are **generated/checked by a script**, never hand-typed. Design docs are stamped point-in-time.

**Why the drift rule is phrased that way:** v1's famous errors ("23-state" when it's 17 nodes; "12 integration tests" when it's 1) were **status claims that went stale**, not design-doc problems. Lighter planning wouldn't have prevented them — generated counts would. That's the precise fix.

### §8 — Voice input

Dictate intent/context/plans (you talk faster than you type, and attaching the *why* becomes free); keyboard for code, paths, identifiers.

### §9 — Skill / tool vetting

The §5.5 bar from CLAUDE.md: read the whole SKILL.md + scripts, grep for network/credential/install calls, pin versions, trial in a throwaway repo, never install mid-task. **Explicitly extended to the §7 mechanisms** — a test-lock hook or eval script is tooling you must vet and maintain too, not free safety.

### §10 — Throughput guardrails

The honest-number rules: verified merges/week is the metric; cycle time is the second dial; WIP = streams you can unblock; no new lane while ≥2 PRs await you; never scale past a red pipeline; keep the queue at lanes × 2; and the memory loop (write-backs, ADRs, retros, generated status) is what compounds.

### §11 — Not adopted, and the honest cons

Three honest admissions: editor migration isn't worth it; the course's **production** Maintain loop doesn't apply (no prod yet — the local version is "post-merge signals auto-file issues": nightly CI failures, eval regressions, cost/drift telemetry #151, LangSmith traces); and **the planning stance is a position, not a law** — the plan-mode discourse is a handful of posts, mostly about general work where output is cheap to check, so the risk tiering is the hedge, and you revisit it if your measured catch-rate ever shows High-tier grilling isn't out-catching Medium-tier intent blocks.

### §12 — Cheat sheet

The whole doc on one screen, keyed by moment (new issue → build → stuck → PR → merge → sprint end → scaling check).

---

## The spine in action — one change at each tier

The fastest way to internalize v2 is to watch the same classifier produce three different workflows:

**Low — "delete the stale HealthLake comparison doc + its README link" (the #20 cleanup).**
Touches only `docs/**` + a root `.md`. → **Low.** The issue body is the whole plan. No design doc, no eval, no locked files. `/validate-and-ship` runs, and it **self-merges** under the standing rule with a `Merged-By` trailer and SHA-bound attestation. Minutes of ceremony.

**Medium — "add a Differential-Freshness-Routing tab to the admin dashboard" (#73).**
Touches portal UI, no PHI, no SQL generation, no model call. → **Medium.** You write a **5–10 line intent block in the PR body** (what/why/constraints/non-goals) instead of a design doc. Targeted tests. **Human merges.** No eval gate (nothing LLM-touching). Moderate ceremony, no new artifact to drift.

**High — "fix the synthesis prompt so `medication_display` isn't NULL" (#111).**
Touches `app/services/sql_synthesis.py` — both cohort semantics *and* LLM-touching. → **High.** Full `grill-with-docs → design doc → ADR`. The eval case sets (`tests/eval/`) and any golden fixtures are **locked** (you can't quietly regenerate expected output to make it pass). The **eval gate is required** once it exists (#136/#137/#142 are open) and must assert it ran N cases with per-domain thresholds. **A human merges, always.** Maximum ceremony — because a wrong cohort/medication mapping is expensive and auditable.

Same one-command pipeline each time; the tier dials the rigor up or down. That's the entire design.

---

## What to set up first (onboarding order)

1. **Internalize §1.** Classifying is the habit everything else rides on.
2. **Stage 0 foundations (§3):** evidence-PR template (§6), the vetting bar (§9), and the golden-file lock + generated-counts check (§7) — these are cheap and high-leverage.
3. **Build the eval gate** (#136/#137/#142) so LLM-touching changes have more than the replay test. CI already runs real tests, including docker compose, on every PR.
4. **Start the catch-rate log (§6)** from day one — it's the metric that later justifies (or refuses) a second lane.
5. **Leave parallelism alone** until §3's Stage-2 trigger is literally true.
