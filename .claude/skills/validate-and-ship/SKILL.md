---
name: validate-and-ship
description: One-invocation pipeline from "code done on a feature branch" to "PR open with evidence, CI watched, merged on green." Runs tests → fresh-context review → conventional commit(s) → rebase → PR with Testing Evidence → SHA-bound attestation → watch CI → attested merge (human merges behavior-touching; standing-rule self-merge for docs/harness only). Use after /tdd finishes an issue, or when the user says "ship this", "validate and ship", "run the pipeline", or "take it from here".
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
Separate latent/defensive fixes from the active change — separate commit minimum (a shared-code bug the feature merely surfaces is its own commit). Message body via a scratchpad file + `git commit -F <file>`: **the Bash approval hook rejects multi-line strings passed inline to `-m`** (control-character guard). End messages with the `Co-Authored-By` trailer the session's attribution instructions specify.

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

   Spell the key exactly `Reviewed-Commit:`. #317, #327, #340 and #348 drifted to `Reviewed commit:`.

3. **Staleness rule:** any commit pushed after this comment voids it. Post-attestation fixes → back through Step 2, then post a NEW attestation comment — never edit or delete an old one; comment ordering is the audit trail. Never merge on a stale attestation. The one exception is 7.4.

4. **Carry-forward across a clean merge from main.** Bringing the branch up to date adds a merge commit, which would void the attestation without changing anything that was reviewed. #283, #287, #290, #291, #292 and #294 merged on attestations voided that way (#361). After attesting, update from main only by merging it (never rebase or force-push), with the merge from main as the last commit and pushed. GitHub's "Update branch" button in its merge mode does exactly this; "Update with rebase" doesn't qualify. Then check the PR's head on GitHub, not a local HEAD.

   `old` is always the **root**: the `Reviewed-Commit` of the newest attestation that is not itself a carry-forward (it has no line starting `- Carried-From:`), i.e. the last real Step 2 review. Take it from the `ROOT` line of the 7.5 reader, which counts only the repo owner's unedited attestations. If the reader prints any `EDITED` line, don't carry forward: stop and report it to the user. Its verdict line must read exactly `- Verdict: SHIP` (SHIP-WITH-FIXES and BLOCK don't qualify). Never chain from an earlier carry: a carry nobody re-verified would launder whatever it let through.

   ```bash
   scripts/attestation.sh carry <PR number> <the ROOT line's commit from the 7.5 reader>
   ```

   It fetches `origin main` and `pull/<n>/head`, prints `NOT-A-MERGE` or each of `main-ok`, `lineage-ok` and `tree-ok` that holds, and exits 0 only when all three print. A final `main=<sha> tree=<sha>` line feeds the comment's Basis line. `main-ok` means the new head's second parent is on `origin/main`. `lineage-ok` means the root is an ancestor of the new head, so nothing was rewritten since the review. `tree-ok` means two things:

   - **No file was changed by both the PR and main since they diverged.** So git never had to merge file contents, and no merge driver, `merge.default` setting, `.gitattributes` or rename-following can shape the result. `-c merge.directoryRenames=false` stops git moving a file the PR added into a directory that main renamed. The #361 review got a real conflict to pass as "clean" through each of those, until this guard replaced an attribute check.
   - **The new head's tree is exactly what git produces by merging the reviewed commit with that main commit.**

   If main touched any of the PR's files, that's a fresh review, even when git merged them cleanly. Only when all three `-ok` lines print, post a NEW attestation comment instead of re-reviewing:

   ```
   ## Review attestation
   - Verdict: SHIP (carried forward)
   - Reviewed-Commit: <$new, full 40-char sha>
   - Carried-From: <$old, the root's Reviewed-Commit, full 40-char sha>
   - Basis: merge from main <$main>; tree <$t> equals merge-tree(Carried-From, main)
   - Reviewer: no new review; carried from the root attestation
   - Findings: as in the root attestation
   ```

   Anything else is a fresh review (Step 2), including any conflict, even one resolved correctly by hand. Don't use `git patch-id` for this: it ignores whitespace and hunk position, so a merge commit that re-indents a `raise` or moves a hunk keeps the same patch-id. The #361 review reproduced both. CI on the new head is still required. It covers integration with main's changes, which a diff review never did (#339 vs #319).

5. **Count only the repo owner's unedited attestations.** The repo is public, so any GitHub user can post a comment headed `## Review attestation` (#368). Read attestations only with this reader. It counts a comment only when the repo owner, the account the pipeline posts with, posted it and nobody has edited it since:

   ```bash
   scripts/attestation.sh read <n>
   ```

   The jq filter lives in that script and nowhere else: the `attestation` status workflow (7.6) runs the same one.

   The reader prints these lines, in this order:
   - `EDITED <url>` for each of the owner's attestations that was edited after it was posted. Anyone with write access can edit any comment, and the comment keeps its original author. An edited attestation never counts, and Step 8 refuses to merge while one exists. gh reports an edit as `includesCreatedEdit`. It has no `lastEditedAt` field.
   - `NEWEST <commit> head|STALE verdict=<…> carried-from=<commit|none>` for the owner's newest attestation. `head` means its `Reviewed-Commit` equals the PR's `headRefOid`.
   - `ROOT <commit> verdict=<…>` for the owner's newest attestation that isn't a carry-forward. This is the root that 7.4 and Step 8 use.
   - `MISSING` in place of both, when the owner has no unedited attestation.
   - `IGNORED <login> <association> <url>` for each attestation that another account posted. Name each one in the merge report: the hand-over for a human merge, or the lane's report for a self-merge. These lines come last, so a flood of forged comments can't push the others down.

   The author must pass two checks. The first is that the login equals the owner's login, which the reader takes from the PR's own URL rather than from a hard-coded name. If the owner renames the account, the URL and every comment show the new login, and a stranger who registers the old login doesn't match. The second is that `authorAssociation` is `OWNER`. gh prints a GitHub App's login without its `[bot]` suffix, so the login alone can't tell the owner from an app of the same name. If the repo moves to an organization, no comment passes either check. The reader then counts nothing, and Step 8 refuses the merge.

6. **The `attestation` status.** `.github/workflows/attestation.yml` runs `scripts/attestation.sh status <n>` on every push to a PR and every comment on one, and posts the result as the commit status `attestation` on the PR's head. `success` means the owner's newest unedited attestation names that head and passes the conditions in Step 8; any other state carries the reason in its description. Once `attestation` is one of `main`'s required checks (the owner adds it), GitHub refuses every merge whose head has no current attestation, by whatever route, the Update branch button included (#466). The workflow never checks out or runs the PR's code: it reads comments through the API and runs git plumbing on fetched objects.
   - Every PR starts with `failure` until you post its attestation. The comment triggers a new run, so nothing needs a manual re-run; allow about a minute.
   - A PR that was open before the check became required has no status until something triggers a run: `gh workflow run attestation.yml -f pr=<n>`.

Honesty note: attestation author and merge actor are the same `gh` account — the value is the timestamped, SHA-bound, append-only record, not identity separation. The 7.5 reader keeps other accounts' attestations and edited ones from counting. It doesn't separate the reviewer from the merge actor, and it can't see a comment that someone with write access deleted. A separate reviewer bot token is a future upgrade, not a claim this design already makes.

### 8. Watch CI; merge by class
Watch the workflow **runs** for the attested SHA (the full 40 characters; a short SHA silently matches no runs), not the check list (background it):

```bash
until gh run list --commit <attested-sha> --json status -q 'length > 0 and all(.[]; .status == "completed")' | grep -qx true; do sleep 45; done
```

Never `gh pr checks --watch`. It exits once every check that *exists* is complete, and a `needs:` job (`security-scan` in `tests.yml`) has no check until its dependencies finish. The watch exited in that ~1s gap, and #203 merged 25s before `security-scan` finished. A run stays `in_progress` until all of its jobs are done, dependent ones included. All PR workflows are created by the same event (#203's three runs share a `createdAt` second), so `length > 0` is enough once the PR is open.

If CI goes red, diagnose and fix — and remember a fix push voids the attestation (Step 7.3). All-green means these print exactly `RUNS OK` and `CHECKS OK`, the second run fresh immediately before merging (gh renders an incomplete check's `completedAt` as `0001-01-01T00:00:00Z`). Anything else, including no output (a gh error), is not green:

```bash
gh run list --commit <attested-sha> --json name,conclusion -q 'if length == 0 then "NO RUNS" else (map(select(.conclusion | IN("success","skipped","neutral") | not) | .name) | if length == 0 then "RUNS OK" else .[] end) end'
gh pr view <n> --json statusCheckRollup -q '.statusCheckRollup | if length == 0 then "NO CHECKS" else (map(select(.completedAt == "0001-01-01T00:00:00Z" or ((.conclusion // .state) | IN("SUCCESS","SKIPPED","NEUTRAL") | not)) | .name // .context) | if length == 0 then "CHECKS OK" else .[] end) end'
```

The first catches a run that failed without creating any check (e.g. a workflow-file error). Then run `scripts/attestation.sh status <n>`. It makes the decision the `attestation` status makes (7.6), and its first field must read `success`:

```bash
scripts/attestation.sh status <n>   # prints: <state><TAB><head sha><TAB><reason>
scripts/attestation.sh read <n>     # for the EDITED and IGNORED lines
```

Anything else, a non-zero exit included, never merges. The reason says which rule failed:
- An owner attestation was edited, which `read` shows as an `EDITED` line → never merge, whatever else is true. An edit breaks the append-only record, so report it to the user, who decides what happens next.
- Missing or stale → back to Step 7.
- A `BLOCK` verdict, or a verdict that isn't `SHIP` or `SHIP-WITH-FIXES`, which includes a carry-forward whose `Carried-From` key is misspelled (the reader can't recognize it as a carry) → never merge.
- A carry-forward whose root isn't verdict `SHIP`, whose `Carried-From` isn't the root's commit, or whose 7.4 checks, re-run now against the root, don't all pass → fresh review (Step 2).

Name each `IGNORED` line from `read` in the merge report (the hand-over for a human merge, the lane's report for a self-merge). The GitHub rollup above includes the posted `attestation` status once it exists; this command is the check that doesn't wait for the workflow.

Then classify by the actual file list (`gh pr view <n> --json files -q '.files[].path'`), not the title prefix:

- **Standing-rule self-merge** — every path is docs-only OR harness-internal. Docs-only = `docs/**` plus *root-level* `*.md` (a `.md` inside `app/`, `tests/`, etc. is behavior-touching — the behavior-touching list wins any conflict), AND the PR title carries the `docs:` prefix (an additional requirement on top of the file-list classifier, not a substitute for it). Harness-internal = `.claude/**`, `scripts/lane.sh`, `scripts/dials.sh`, `docs/DAILY_DEV_WORKFLOW.md`, `CLAUDE.md`. A PR mixing the two classes takes the `harness-internal` trailer. Write the squash body to a scratch file — PR summary, `Closes #<issue>`, trailer `Merged-By: pipeline (standing-rule: docs-only)` (or `harness-internal`), then `Co-Authored-By`. Then enable auto-merge, with the same head SHA and the same body:
  `gh pr merge <n> --squash --auto --match-head-commit <attested-sha> --body-file <file>`
  Use `--auto` only when both of these print `true`:
  `gh api repos/{owner}/{repo} -q .allow_auto_merge`
  `gh api repos/{owner}/{repo}/branches/main/protection/required_status_checks -q '.contexts | index("attestation") != null'`
  If either doesn't, merge at once instead:
  `gh pr merge <n> --squash --delete-branch --match-head-commit <attested-sha> --body-file <file>`
  Why both: auto-merge fires on whatever head the PR has when its required checks pass, and the required `attestation` status (7.6) is what stops a head pushed after this attestation from merging unattested. `--match-head-commit` is still checked when `--auto` merges at once: `gh` sends `expectedHeadOid`, the squash body and the merge method, and a wrong SHA was refused (#466 test). Whether GitHub re-checks that SHA when a delayed auto-merge fires is untested, which is why the required status is a precondition and not an extra.
  `--delete-branch` isn't passed with `--auto`, because the merge can happen after `gh` exits. Wait for it (background it), then delete the branch yourself:
  `until [ "$(gh pr view <n> --json state -q .state)" != OPEN ]; do sleep 45; done`
  `MERGED` → `git push origin --delete <branch>` and delete the local branch. `CLOSED`, or a check that went red → `gh pr merge <n> --disable-auto`, diagnose and fix as above.
  **Self-amendment carve-out:** a PR that changes the merge policy itself — this skill file, CLAUDE.md's "Merge actor" rule, or the workflow doc's merge sections — is ALWAYS human-merge, whatever else it touches. The pipeline never self-merges a change to its own merge authority.
- **Human merge (everything else)** — any path under `app/**`, `tests/**`, `migrations/**`, `config/**`, CI workflows, or dependency files is behavior-touching. Report green + the attested SHA, post the ready-to-run merge command (with `--match-head-commit` filled in), and STOP. The human merges; you wait. No framing makes a behavior-touching PR self-mergeable.

Either class, after merge: `git checkout main && git pull --ff-only`, delete the local branch.

### 9. Lane close
If the user corrected anything this lane, write one dated line to memory or `.claude/architecture.rules` before the next issue. Cross-link any findings routed to other issues.

## Escalate, don't guess
Stop and ask the user for: behavior-changing review findings, scope changes, anything destructive, or a red CI you can't attribute. Everything else runs to merge without you.
