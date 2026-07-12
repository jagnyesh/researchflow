---
name: validate-and-ship
description: One-invocation pipeline from "code done on a feature branch" to "PR open with evidence, CI watched, merged on green." Runs tests → fresh-context review → conventional commit(s) → rebase → PR with Testing Evidence → watch CI → squash-merge. Use after /tdd finishes an issue, or when the user says "ship this", "validate and ship", "run the pipeline", or "take it from here". Distilled from Sprint 6.7's per-issue continuous-merge workflow (docs/DAILY_DEV_WORKFLOW.md §5.8).
---

# validate-and-ship

The composite pipeline for this repo's per-issue-branch, continuous-merge workflow. One invocation takes a finished change from a feature branch to a merged PR. Escalate only genuine decisions; everything mechanical runs autonomously.

**Preconditions:** you are on a `feat/<issue>-<slug>` or `fix/<issue>-<slug>` branch, the change is implemented, and its tests exist. If not, stop and say so.

## The steps

### 1. Run the change's tests
Run the tests covering this change with the project venv: `./.venv/bin/pytest <paths> -q`. If the change touches a runtime surface (agents, SQL, API, UI), also drive it end-to-end (the gated integration test, a live probe, or a `requires_services` run) — green unit tests alone do NOT clear the bar. This repo has two wire-level bugs on record that passed unit tests for months; assert at the wire/DB, not just the wrapper. Capture the actual command output — it fills the PR's Testing Evidence section verbatim.

### 2. Fresh-context review (the load-bearing step)
Spawn a **clean** reviewer subagent (`general-purpose`, `run_in_background: false`) on the diff. NEVER review in this authoring session — it checks its own homework. Give the reviewer: the issue's acceptance criteria, the ADR/design authority, the explicit out-of-scope list, and instructions to probe empirically (parse/execute against real state, not static reading) and report CONFIRMED vs suspected findings with a SHIP / SHIP-WITH-FIXES / BLOCK verdict.

**For security-sensitive changes (auth, SQL synthesis, PHI boundaries, validation gates, crypto): the review is adversarial AND repeated.** Send fixes back to the SAME reviewer (SendMessage to its agentId) and re-run until a pass returns zero confirmed escapes. Sprint 6.7 #95 took six passes; the escapes narrowed each round (that monotonic narrowing is the convergence signal). A green test suite proves nothing about shapes it omits — every confirmed escape becomes an explicit regression case before re-running.

### 3. Triage findings
- **Mechanical** (naming, dead code, lint, a missing test case, a clear bug in the new code): fix silently, re-run tests.
- **Behavior-changing or scope questions**: escalate to the user. Don't decide product scope.
- A BLOCK on your own new code is not an escalation — it's a bug to fix, then re-review.

### 4. Conventional commit(s)
Separate latent/defensive fixes from the active change — separate commit minimum (a shared-code bug the feature merely surfaces is its own commit). Message body via a scratchpad file + `git commit -F <file>`: **the Bash approval hook rejects multi-line strings passed inline to `-m`** (control-character guard). End messages with the `Co-Authored-By: Claude Fable 5` trailer.

Stage files **explicitly by path** — never `git add -A` (it sweeps in untracked `.pptx`, checkpoint db files, `.lean-ctx/`). Expect the pre-commit hook to reformat files and abort the first commit (HEAD unchanged, files show `MM`); when that happens, re-stage the exact paths (plus `.secrets.baseline` if the detect-secrets hook touched it) and re-commit. Confirm the commit landed with `git log --oneline -1`.

### 5. Rebase + push
Rebase onto latest `main`, push the branch: `git push -u origin <branch>`.

### 6. Open the PR with Testing Evidence
`gh pr create --base main --head <branch> --body-file <file>` (multi-line body → file, same hook reason). Include `Closes #<issue>` and a **Testing evidence** section: commands run + real output, E2E exercised (what was driven, expected vs observed), review verdict + how findings were handled, and what's not covered and why. If the change is behind a flag or has a do-not-flip guardrail, state it and post it on the owning issue.

### 7. Watch CI, merge on green
`gh pr checks <n> --watch --interval 45` (background it). On all-green: `gh pr merge <n> --squash --delete-branch`, then `git checkout main && git pull --ff-only` and delete the local branch. If CI goes red, diagnose and fix — don't merge.

### 8. Lane close
If the user corrected anything this lane, write one dated line to memory or `.claude/architecture.rules` before the next issue. Cross-link any findings routed to other issues.

## Escalate, don't guess
Stop and ask the user for: behavior-changing review findings, scope changes, anything destructive, or a red CI you can't attribute. Everything else runs to merge without you.
