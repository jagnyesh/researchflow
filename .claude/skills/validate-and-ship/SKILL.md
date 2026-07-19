---
name: validate-and-ship
description: One-invocation pipeline from "code done on a feature branch" to "PR open with evidence, CI watched, merged on green." Runs tests → fresh-context review → conventional commit(s) → rebase → PR with Testing Evidence → SHA-bound attestation → watch CI → attested merge (human merges behavior-touching; standing-rule self-merge for docs/harness only). Use after /tdd finishes an issue, or when the user says "ship this", "validate and ship", "run the pipeline", or "take it from here". Distilled from Sprint 6.7's per-issue continuous-merge workflow (docs/DAILY_DEV_WORKFLOW.md §5.8).
---

# validate-and-ship

The composite pipeline for this repo's per-issue-branch, continuous-merge workflow. One invocation takes a finished change from a feature branch to a merged PR. Escalate only genuine decisions; everything mechanical runs autonomously.

**Preconditions:** you are on a `feat/<issue>-<slug>` or `fix/<issue>-<slug>` branch, the change is implemented, and its tests exist. If not, stop and say so.

## The steps

### 1. Run the change's tests
Run the tests covering this change with the project venv: `./.venv/bin/pytest <paths> -q`. If the change touches a runtime surface (agents, SQL, API, UI), also drive it end-to-end (the gated integration test, a live probe, or a `requires_services` run) — green unit tests alone do NOT clear the bar. This repo has two wire-level bugs on record that passed unit tests for months; assert at the wire/DB, not just the wrapper. Capture the actual command output — it fills the PR's Testing Evidence section verbatim.

### 2. Fresh-context review (the load-bearing step)
Spawn a **clean** reviewer subagent (`general-purpose`, `run_in_background: false`) on the diff. NEVER review in this authoring session — it checks its own homework. Give the reviewer: the issue's acceptance criteria, the ADR/design authority, the explicit out-of-scope list, and instructions to probe empirically (parse/execute against real state, not static reading) and report CONFIRMED vs suspected findings with a SHIP / SHIP-WITH-FIXES / BLOCK verdict. The reviewer's final message must end with a liftable verdict block — the verdict plus one line per finding with its disposition — saved to a scratch file: it becomes the Step 7 attestation comment verbatim.

**For security-sensitive changes (auth, SQL synthesis, PHI boundaries, validation gates, crypto): the review is adversarial AND repeated.** Send fixes back to the SAME reviewer (SendMessage to its agentId) and re-run until a pass returns zero confirmed escapes. Sprint 6.7 #95 took six passes; the escapes narrowed each round (that monotonic narrowing is the convergence signal). A green test suite proves nothing about shapes it omits — every confirmed escape becomes an explicit regression case before re-running.

### 3. Triage findings
- **Mechanical** (naming, dead code, lint, a missing test case, a clear bug in the new code): fix silently, re-run tests.
- **Behavior-changing or scope questions**: escalate to the user. Don't decide product scope.
- A BLOCK on your own new code is not an escalation — it's a bug to fix, then re-review.
- Any fix applied after the review is only covered by a fresh attestation (Step 7 staleness rule); a fix that changes behavior goes back through Step 2 before it can be attested.

### 4. Conventional commit(s)
Separate latent/defensive fixes from the active change — separate commit minimum (a shared-code bug the feature merely surfaces is its own commit). Message body via a scratchpad file + `git commit -F <file>`: **the Bash approval hook rejects multi-line strings passed inline to `-m`** (control-character guard). End messages with the `Co-Authored-By: Claude Fable 5` trailer.

Stage files **explicitly by path** — never `git add -A` (it sweeps in untracked `.pptx`, checkpoint db files, `.lean-ctx/`). Expect the pre-commit hook to reformat files and abort the first commit (HEAD unchanged, files show `MM`); when that happens, re-stage the exact paths (plus `.secrets.baseline` if the detect-secrets hook touched it) and re-commit. Confirm the commit landed with `git log --oneline -1`.

### 5. Rebase + push
Rebase onto latest `main`, push the branch: `git push -u origin <branch>`.

### 6. Open the PR with Testing Evidence
`gh pr create --base main --head <branch> --body-file <file>` (multi-line body → file, same hook reason). Include `Closes #<issue>` and a **Testing evidence** section: commands run + real output, E2E exercised (what was driven, expected vs observed), review verdict + how findings were handled, and what's not covered and why. If the change is behind a flag or has a do-not-flip guardrail, state it and post it on the owning issue.

**Artifacts are pipeline-generated, keyed on what the diff touches** — never left to memory at PR-writing time. All artifacts are text (`gh` cannot attach images to PR bodies or comments; screenshots are not a valid artifact class):
- Diff touches `app/web_ui/**` → run the Streamlit AppTest covering the touched surface (pattern: `tests/test_researcher_portal_download_ui.py`) and paste the verbatim output. Claims about rendered state cite AppTest assertions, not screenshot descriptions. If the touched surface has no AppTest, say so under "Not covered" — don't fabricate a substitute.
- The PR makes an LLM or wire-level claim (prompt change, provider adapter, SQL synthesis, caching) → a LangSmith trace URL for the driven run, or the dumped request payload (keys redacted) as fenced text.
- Everything else → the verbatim Step 1 command output (the current norm).
- **Carve-out:** a `docs:`-prefixed PR whose diff is docs-only skips the Testing Evidence section — write `Testing evidence: n/a (docs-only)`. Fabricated evidence on a docs PR is worse than none.

### 7. Post the SHA-bound review attestation
The Step 2 verdict must live on the PR as a comment bound to the exact commit it covers — prose in the PR body is not attestation (it isn't timestamped against pushes). Immediately after the PR opens:

1. `sha=$(git rev-parse HEAD)` — confirm it equals `gh pr view <n> --json headRefOid -q .headRefOid` (you just pushed it; mismatch → stop and reconcile).
2. Write the attestation to a scratch file (multi-line → file, hook rule), then `gh pr comment <n> --body-file <file>`:

   ```
   ## Review attestation
   - Verdict: SHIP | SHIP-WITH-FIXES | BLOCK
   - Reviewed-Commit: <full 40-char sha>
   - Reviewer: fresh-context subagent (Step 2), <k> pass(es)
   - Findings: <one per line: finding → disposition (fixed / accepted / routed to #issue)>
   ```

3. **Staleness rule:** any commit pushed after this comment voids it. Post-attestation fixes → back through Step 2, then post a NEW attestation comment — never edit the old one; comment ordering is the audit trail. Never merge on a stale attestation.

Honesty note: attestation author and merge actor are the same `gh` account — the value is the timestamped, SHA-bound, append-only record, not identity separation. A separate reviewer bot token is a future upgrade, not a claim this design already makes.

### 8. Watch CI; merge by class
`gh pr checks <n> --watch --interval 45` (background it). If CI goes red, diagnose and fix — and remember a fix push voids the attestation (Step 7.3). On all-green, verify the NEWEST attestation comment's `Reviewed-Commit` equals `gh pr view <n> --json headRefOid -q .headRefOid`; mismatch → back to Step 7, never merge. Then classify by the actual file list (`gh pr view <n> --json files -q '.files[].path'`), not the title prefix:

- **Standing-rule self-merge** — every path is docs-only OR harness-internal. Docs-only = `docs/**` plus *root-level* `*.md` (a `.md` inside `app/`, `tests/`, etc. is behavior-touching — the behavior-touching list wins any conflict), AND the PR title carries the `docs:` prefix (an additional requirement on top of the file-list classifier, not a substitute for it). Harness-internal = `.claude/**`, `scripts/lane.sh`, `scripts/dials.sh`, `docs/DAILY_DEV_WORKFLOW.md`, `CLAUDE.md`. A PR mixing the two classes takes the `harness-internal` trailer. Write the squash body to a scratch file — PR summary, `Closes #<issue>`, trailer `Merged-By: pipeline (standing-rule: docs-only)` (or `harness-internal`), then `Co-Authored-By` — and merge:
  `gh pr merge <n> --squash --delete-branch --match-head-commit <attested-sha> --body-file <file>`
  `--match-head-commit` makes GitHub itself refuse the merge if the head moved after attestation — server-side enforcement, not discipline.
  **Self-amendment carve-out:** a PR that changes the merge policy itself — this skill file, CLAUDE.md's "Merge actor" rule, or the workflow doc's merge sections — is ALWAYS human-merge, whatever else it touches. The pipeline never self-merges a change to its own merge authority.
- **Human merge (everything else)** — any path under `app/**`, `tests/**`, `migrations/**`, `config/**`, CI workflows, or dependency files is behavior-touching. Report green + the attested SHA, post the ready-to-run merge command (with `--match-head-commit` filled in), and STOP. The human merges; you wait. No framing makes a behavior-touching PR self-mergeable.

Either class, after merge: `git checkout main && git pull --ff-only`, delete the local branch.

### 9. Lane close
If the user corrected anything this lane, write one dated line to memory or `.claude/architecture.rules` before the next issue. Cross-link any findings routed to other issues.

## Escalate, don't guess
Stop and ask the user for: behavior-changing review findings, scope changes, anything destructive, or a red CI you can't attribute. Everything else runs to merge without you.
