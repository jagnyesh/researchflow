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

**Red-first check.** A PR that adds or changes a test for a behavior change proves the test can fail: run `scripts/red_first.sh [--code <path>]... <test files or file::node ids>` from the repo root before the review. Give `file::node` ids for tests you added to or changed in an existing file: a bare file counts as red when any one test in it fails on the base, so an unrelated passing test hides behind it (the script only notes how many tests passed there). The script runs each target once on a temporary worktree at the merge-base with `origin/main` and once here. The worktree gets the named test files plus every test-support file the change touches: anything under `tests/`, any `conftest.py`, and the root `pytest.ini`, `pyproject.toml`, `setup.cfg` and `tox.ini`. When the code under test itself lives under `tests/` (the eval harness modules, such as `tests/eval/harness.py` or `tests/eval/formal_predicates.py`), name each such file or directory with `--code <path>` (repeatable). The script then leaves it at its base version, or absent when the change adds it, and a `Red-first note:` line lists what it held back (on an exit 1 where the target passes on the base, the error names it too). Name harness modules only, never case data or fixtures: a held data file makes the base red for a missing file, not for the code, so check the held list. Without `--code`, the change's harness is copied to the base and the target passes there, which reads as exit 1. "Here" is the working tree, committed or not. Exit codes:

- **0**: the base run is red and at least one test passed here. A `Red-first note:` line after it flags a base red that is only a collection error (it proves the test needs the change in order to import, not that an assertion can fail) and a file with tests that pass on the base.
- **1**: the test passes on the base, collects nothing there, or fails here, or no test passed here (an all-skipped run isn't green).
- **2**: nothing ran. Usage error (an option without its value, a bad `RED_FIRST_TIMEOUT`, a missing path, a `--code` path that exists neither here nor on the base or that holds a target, no merge-base with `origin/main`: pass `--base <ref>`), or a path on `.claude/lane-never-run.txt`, matched by file, so a symlink or a case variant is refused too.
- **3**: the code under test would import from this checkout instead of the base tree. The import-path check probes the `app` package; for code in other top-level packages set `RED_FIRST_PACKAGE`, comma-separated.
- **4**: a run timed out (`RED_FIRST_TIMEOUT`, default 600 seconds) or pytest itself broke (pytest exit 3, 4 or 6, or `RED_FIRST_PYTHON` can't run it).

A non-zero exit is a finding to fix, not a check to skip: a test that can't fail isn't evidence. In the PR, the `- Red-first:` item holds the script's `Red-first:` line, one per target, with its base output block fenced underneath and any `Red-first note:` lines kept. The line names the commit it ran on, with `+uncommitted` after the SHA when the tree was dirty, so commit before the PR and re-run if the code changed after the check. A docs-only, prose-only or pure-refactor PR has no red step and writes `Red-first: n/a (<reason>)`; the Step 2 reviewer checks that reason against the diff.

Every PR body carries the line, docs-only ones included, because the required `attestation` status (Step 7.6) checks for it (#542). The status fails a body with no line starting `Red-first:`, a line whose value is empty or the template's `<...>` placeholder, and an `n/a` without a reason in parentheses. The label line itself needs a value, so with several targets put the first script line on the `- Red-first:` line and the rest under it. It doesn't judge the content: prose for a manual equivalent passes, and the Step 2 reviewer judges it. To fix a failure, edit the PR body. The edit re-runs the check, and no push is needed.

### 2. Fresh-context review (the load-bearing step)
Spawn a **clean** reviewer subagent (`general-purpose`, `run_in_background: false`) on the diff. NEVER review in this authoring session — it checks its own homework. Give the reviewer: the issue's acceptance criteria, the ADR/design authority, the explicit out-of-scope list, the Step 1 `Red-first:` line (the script's output, or the `n/a` reason) with a request to say in its report whether it holds against the diff, and instructions to probe empirically (parse/execute against real state, not static reading) and report CONFIRMED vs suspected findings with a SHIP / SHIP-WITH-FIXES / BLOCK verdict. The reviewer's final message must end with a liftable verdict block — the verdict plus one line per finding with its disposition — saved to a scratch file: it feeds the Step 7 attestation comment (one reviewer: verbatim; High tier: combined per the Step 7 template).

**High tier (§1's classifier): a second reviewer on Fable.** After the first reviewer's pass, spawn a second clean subagent (`general-purpose`, `run_in_background: false`) with `model: "fable"`. §1's "Model, effort" notes record that the owner named Fable for this role (standing choice, High-tier second reviewer only); the first reviewer stays on the lane's model. It receives the same inputs as the first (diff, acceptance criteria, ADR/design authority, out-of-scope list) plus the first reviewer's confirmed findings, and nothing from the authoring session's reasoning, so it stays independent. It does two things: re-checks each confirmed finding by reproducing it against real state and marks it confirmed or refuted with the evidence, and reviews the diff on its own for what the first missed. It ends with the same liftable verdict block. Low and Medium tiers keep one reviewer.

**For security-sensitive changes (auth, SQL synthesis, PHI boundaries, validation gates, crypto): the review is adversarial AND repeated.** Send fixes back to the SAME reviewer (SendMessage to its agentId) and re-run until a pass returns zero confirmed escapes. Sprint 6.7 #95 took six passes; the escapes narrowed each round (that monotonic narrowing is the convergence signal). A green test suite proves nothing about shapes it omits — every confirmed escape becomes an explicit regression case before re-running. The repeat loop runs on the first reviewer only; the Fable second reviewer then reviews the final commit once, and again only if its findings lead to fixes.

### 3. Triage findings
- **Mechanical** (naming, dead code, lint, a missing test case, a clear bug in the new code): fix silently, re-run tests.
- **Behavior-changing or scope questions**: escalate to the user. Don't decide product scope. When the user chooses to keep the behavior as the reviewer found it, the disposition is `accepted`.
- **A finding outside the PR's acceptance criteria** takes the first disposition below that applies. The starting values (30 lines, one issue) are the owner's; tune them against the follow-ups-per-PR dial from `scripts/review_metrics.py` (#520).
  1. **Fixed here**, as its own commit (Step 4), when the fix is in a file the PR already changes, is the same tier or lower, needs no design decision, and is at most 30 changed lines.
  2. **Routed to #issue** by a comment on an existing open issue, when a search finds one that covers it. Record it as `routed to #<n>`.
  3. **Filed #issue** as a new issue, only when the reviewer reproduced the finding and it gives a wrong result, a security or PHI exposure, or a crash on a supported path. The command and its observed output go in the issue body. Label it `needs-triage`, never `ready-for-agent`: the owner promotes it. Record it as `filed #<n>`.
  4. **Noted, not filed** for everything else. It is recorded on the attestation's Findings line and goes no further.

  A PR files at most one new issue. A second needs the owner's OK; the default is one issue with a checklist.
- A finding either reviewer confirms goes through this triage. A High-tier PR is `SHIP` only when both reviewers return `SHIP`; any other combination is the worse of the two verdicts.
- A BLOCK on your own new code is not an escalation — it's a bug to fix, then re-review.
- Any fix applied after the review is only covered by a fresh attestation (Step 7 staleness rule); a fix that changes behavior goes back through Step 2 (both reviewers on High tier) before it can be attested.

### 4. Conventional commit(s)
Separate latent/defensive fixes from the active change — separate commit minimum (a shared-code bug the feature merely surfaces is its own commit). Message body via a scratchpad file + `git commit -F <file>`: **the Bash approval hook rejects multi-line strings passed inline to `-m`** (control-character guard). End messages with the `Co-Authored-By` trailer the session's attribution instructions specify.

Stage files **explicitly by path** — never `git add -A` (it sweeps in untracked `.pptx`, checkpoint db files, `.lean-ctx/`). Expect the pre-commit hook to reformat files and abort the first commit (HEAD unchanged, files show `MM`); when that happens, re-stage the exact paths (plus `.secrets.baseline` if the detect-secrets hook touched it) and re-commit. Confirm the commit landed with `git log --oneline -1`.

### 5. Rebase + push
Rebase onto latest `main`, push the branch: `git push -u origin <branch>`.

### 6. Open the PR with Testing Evidence
`gh pr create --base main --head <branch> --body-file <file>` (multi-line body → file, same hook reason). Include `Closes #<issue>` and a **Testing evidence** section whose first line is exactly `- Risk tier: <low|medium|high> — paths: <the paths that set it>` (the template in `docs/DAILY_DEV_WORKFLOW.md` §6; `scripts/review_metrics.py` reads it, and the docs-only carve-out below still writes it). Then the §6 template's lines, in its order: `Red-first:` (the script's line and base output, or `Red-first: n/a (<reason>)`, Step 1), commands run + real output, E2E exercised (what was driven, expected vs observed), `Eval gate (if LLM-touching):`, `Artifacts:`, `Follow-ups:` (per Step 3: `filed #<n>`, `routed to #<n>` or none) and what's not covered and why. The review verdict isn't a line here; it lives in the Step 7 attestation. If the change is behind a flag or has a do-not-flip guardrail, state it and post it on the owning issue.

**Artifacts are pipeline-generated, keyed on what the diff touches** — never left to memory at PR-writing time. All artifacts are text (`gh` cannot attach images to PR bodies or comments; screenshots are not a valid artifact class):
- Diff touches `app/web_ui/**` → run the Streamlit AppTest covering the touched surface (pattern: `tests/test_researcher_portal_download_ui.py`) and paste the verbatim output. Claims about rendered state cite AppTest assertions, not screenshot descriptions. If the touched surface has no AppTest, say so under "Not covered" — don't fabricate a substitute.
- The PR makes an LLM or wire-level claim (prompt change, provider adapter, SQL synthesis, caching) → a LangSmith trace URL for the driven run, or the dumped request payload (keys redacted) as fenced text.
- Everything else → the verbatim Step 1 command output (the current norm).
- **Carve-out:** a `docs:`-prefixed PR whose diff is docs-only skips the Testing Evidence section — write `Testing evidence: n/a (docs-only)`, with the `- Risk tier:` line first and `- Red-first: n/a (docs-only)` after it (Step 1: the required status checks for the line). Fabricated evidence on a docs PR is worse than none.

### 7. Post the SHA-bound review attestation
The Step 2 verdict must live on the PR as a comment bound to the exact commit it covers — prose in the PR body is not attestation (it isn't timestamped against pushes). Immediately after the PR opens:

1. `sha=$(git rev-parse HEAD)` — confirm it equals `gh pr view <n> --json headRefOid -q .headRefOid` (you just pushed it; mismatch → stop and reconcile).
2. Write the attestation to a scratch file (multi-line → file, hook rule), then `gh pr comment <n> --body-file <file>`:

   ```
   ## Review attestation
   - Verdict: SHIP | SHIP-WITH-FIXES | BLOCK
   - Reviewed-Commit: <full 40-char sha>
   - Reviewer 1 (<model>): fresh-context subagent (Step 2), <k> pass(es), <verdict>
   - Reviewer 2 (<model>): fresh-context subagent (Step 2), <k> pass(es), <verdict>
   - Findings:
     - finding <n>: <text> → <disposition>
   ```

   Findings format (`scripts/review_metrics.py` parses it): one finding per line, nested under `- Findings:`, as `  - finding <n>: <text> → <disposition>`. The disposition starts with one of `fixed`, `accepted`, `filed #<n>` (a new issue), `routed to #<n>` (a comment on an existing open issue) or `noted, not filed` (Step 3). A `filed #<n>` names the new issue that counts as a follow-up (§6). Several issues are written `#a, #b` or `#a and #b`. Write `- Findings: none` when the review found nothing. A note about the review process goes on its own line starting `  - process:` and isn't a finding.

   Before posting, run `python3 scripts/review_metrics.py --check-body <file>` on the scratch file. It uses the parser the metrics use, prints each problem as `attestation format: ...` and exits 1; fix the file and re-run until it prints `attestation format ok`. It also refuses a body whose `- Reviewed-Commit:` line is missing, misspelled or not 40 hex characters.

   The required `attestation` status (7.6) runs the same parser on the root attestation, the one the 7.5 reader prints as `ROOT` (#542). The status fails when a problem leaves a metric empty: no `- Findings:` line, a nested line that isn't `finding <n>:`, a finding with a missing or unknown disposition, inline text other than `none`, a blank line inside the block, or no pass count on a Reviewer line. #536 and #539 merged with roots like that. Soft warnings that `--check-body` also prints, such as an attestation that files two issues, don't fail the status. A carry-forward's own `Findings: as in the root attestation` isn't checked. To fix a root that fails, post a new attestation for the same commit, with the same verdict and findings written in the format, and leave the old one unedited. That corrects the record without a new review, so it needs no Step 2 pass. If the PR's newest attestation is a carry-forward, post a new carry-forward from the corrected root afterwards (7.4), because the newest attestation must name the head.

   Include the `Reviewer 2` line on High-tier PRs only. The `Verdict:` line is the combined verdict (the worse of the two on a High-tier PR). Per-reviewer lines never start with `- Verdict:`, because the 7.5 reader matches that line exactly. Spell the key exactly `Reviewed-Commit:`. #317, #327, #340 and #348 drifted to `Reviewed commit:`.

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
   - The status records a decision made when a run last executed. A failed or missed run leaves the previous status on that commit, so a status that disagrees with `scripts/attestation.sh status <n>` is stale: Step 8 trusts the command, and a new run replaces the status.
   - Every PR starts with `failure` until you post its attestation. The comment triggers a new run, so nothing needs a manual re-run; allow about a minute.
   - A PR that was open before the check became required has no status until something triggers a run: `gh workflow run attestation.yml -f pr=<n>`.
   - Since #542, `success` also needs the root's Findings to parse (7.2) and the PR body to carry a filled `Red-first:` line (Step 1). These run only where the status would otherwise pass, so a missing, stale or BLOCK attestation reports that first. An edit to the PR body triggers a run too. Merged PRs are never re-checked. A PR that was open when #542 merged keeps its posted status until its next push, comment or edit, and Step 8's `scripts/attestation.sh status` applies the new rules at once.

Honesty note: attestation author and merge actor are the same `gh` account — the value is the timestamped, SHA-bound, append-only record, not identity separation. The 7.5 reader keeps other accounts' attestations and edited ones from counting. It doesn't separate the reviewer from the merge actor, and it can't see a comment that someone with write access deleted. A separate reviewer bot token is a future upgrade, not a claim this design already makes.

### 8. Watch CI; merge by class
Watch the workflow **runs** for the attested SHA (the full 40 characters; a short SHA silently matches no runs), not the check list (background it):

```bash
until gh run list --commit <attested-sha> --json status -q 'length > 0 and all(.[]; .status == "completed")' | grep -qx true; do sleep 45; done
```

Never `gh pr checks --watch`. It exits once every check that *exists* is complete, and a `needs:` job has no check until its dependencies finish (`security-scan` in `tests.yml` had `needs: test` until #463). The watch exited in that ~1s gap, and #203 merged 25s before `security-scan` finished. A run stays `in_progress` until all of its jobs are done, dependent ones included. All PR workflows are created by the same event (#203's three runs share a `createdAt` second), so `length > 0` is enough once the PR is open.

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
- The root's Findings don't parse → post a corrected attestation for the same commit (7.2). No new review.
- The PR body has no filled `Red-first:` line, or an `n/a` with no reason → edit the PR body (Step 1).

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
If the user corrected anything this lane, write one dated line to `CLAUDE.md` or `.claude/architecture.rules` before the next issue. Cross-link any findings routed to other issues.

## Escalate, don't guess
Stop and ask the user for: behavior-changing review findings, scope changes, anything destructive, or a red CI you can't attribute. Everything else runs to merge without you.
