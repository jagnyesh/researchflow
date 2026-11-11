---
name: plan-lanes
description: Plans and launches issue lanes for this repo. Checks the §3/§10 guardrails (branch protection, main green, review debt, WIP), verifies and risk-tiers the open ready-for-agent issues, predicts each one's files and finds overlap, drafts lane briefs, and after the user approves starts one worktree session per issue (/tdd then /validate-and-ship; High tier starts with /grill-with-docs). It then watches main after each merge and stops launching when main goes red. Use when the user wants to work through the ready-for-agent queue, start the next issue or two, or plan lanes.
disable-model-invocation: true
---

# plan-lanes

Run this skill in a fresh session on Opus at medium effort (`docs/DAILY_DEV_WORKFLOW.md` §1). Lanes inherit this session's model and effort unless Step 5 sets them.

Plan, ask, launch, watch. Launching is cheap and reversible: each lane is its own branch in its own folder. Merging is where separate changes first meet. This skill adds no merge rule of its own:
- lanes ship through `/validate-and-ship` unchanged;
- `main`'s "require branches to be up to date" protection forces every PR to pass its required checks on the latest main before it can merge, so merges serialize;
- this session's job at merge time is to check and report.

Required checks don't cover everything: the code-scanning `CodeQL` check isn't required (the `codeql-analysis (python)` job is), and Container Security Scan runs only on push to main. So main can still go red after a merge, which is why Step 6 watches it.

Authorities, by reference: risk tiers `docs/DAILY_DEV_WORKFLOW.md` §1, the Stage-2 trigger §3, guardrails §10, attestation templates and merge rules `.claude/skills/validate-and-ship/SKILL.md` Steps 7–8.

## 1. Pre-flight (read-only)

Run `.claude/skills/plan-lanes/preflight.sh`. It runs git and gh queries only, and the one local change is fetching `origin/main`. A nonzero exit or any `ERROR:` line means the report is incomplete: fix the cause or tell the user, and don't plan on a blank section. Then read its sections:

1. **Protection:** must print `true`. Otherwise the override's premise is gone and the cap is 2 (§3). Say why.
2. **Pipeline:** `MAIN OK`, or the runs that aren't green. If a run is queued or in progress, wait and re-run; don't plan on an unknown main. The 7-day list shows push runs that failed, or that passed only on a re-run. Treat main as flaky if a run passed with `attempt` > 1, or if a workflow failed and then passed on a later commit that didn't fix it. A re-run that failed again is a real failure, not a flake.
3. **Open PRs:**
   - **Review debt:** the green, non-draft ones, each waiting on your merge, plus any lane waiting on your answer.
   - **Wait:** every non-draft open PR, green or not, shows how long it has waited on you since its first `SHIP` attestation. That's §3's definition; dials.sh's green→merge restarts on every update from main. `OVER 24h` marks one past the bar.
4. **Override health:** whether the §3 override is in force on `origin/main`, meaning both its doc block and `WIP_LIMIT=4` are there. If so, it shows its revert triggers for every merge since the override landed:
   - merged PRs that waited over 24 h;
   - failed, timed-out or never-started push runs on main;
   - revert commits.
   The other escapes (§6: reopened issues, bugs filed against those PRs) aren't scripted, so ask the user. If any trigger shows, tell the user the doc says to revert to 2 (§3 says how). The cap is 2 until they decide. A failed run they attribute to something outside the merged PRs doesn't count. A PR "merged without a SHIP attestation" isn't a §3 trigger: its wait can't be measured and it may be a merge-policy breach, so ask the user. This section is the data §3's log (`docs/audits/lane-cap-override.md`) records, along with any attribution, so offer to add it there, creating the file if it doesn't exist yet.
5. **WIP:** §3 counts every worktree other than the main checkout whose PR isn't merged or closed, a lane with no commits yet included, plus cloud sessions. So a worktree counts as an active lane unless:
   - its PR is `MERGED` or `CLOSED`;
   - it's marked `this-checkout` with 0 commits ahead and no open PR (the checkout you're planning from; run the skill from the main checkout when you can);
   - it's detached with 0 commits ahead, or `prunable`. This exemption is the skill's own reading: such a checkout has no branch or no folder, so it can't be a lane.

   A branch with 0 commits ahead and no PR counts unless the user says it's a scratch checkout. A branch with commits ahead and no PR is live, unreviewed work, and it counts. Ask the user about cloud sessions and any other lane with no local worktree. Merged or closed lanes are cleanup candidates for Step 4.
6. **Plan limits:** the account's plan limits, read from the app's usage report when the session has one, otherwise "not available". Show the row at the gate; the owner decides whether to launch. Don't write the figures into any committed file.
7. **Queue:** the ready-for-agent count, against lanes × 2.

**New lanes allowed.** The rules are the §3 override's, applied in this order:
1. **Cap C:** 4 while the override is on `origin/main`, protection is `true` and no revert trigger stands; otherwise 2.
2. **Main red or flaky:** drop to one lane, the one fixing `main` (§3). It's the only new lane allowed, and it opens whatever review debt or the 24 h gate says (§3), because open lanes can't merge, debt can't drain and waits keep growing until `main` is fixed. §3 doesn't lift the cap: below C it opens, and at C ask the user which open lane pauses or takes the fix. The other lanes hold their merges if the user calls a hold (Step 6). If an open lane is better placed to fix it, ask the user instead of opening one.
3. **0 new lanes** if review debt ≥ 2, or any open PR waited over 24 h.
4. **Otherwise:** 1 − WIP without the trigger. Going up to C − WIP needs at least one lane already mid-run on a long autonomous task, plus the user's confirmation of the rest of the §3 Stage-2 trigger for each extra lane. Each clause is its own row in Step 4:
   - the new issue is independent and well-specified;
   - review is keeping up (§10): escalations per lane are low, which is the user's judgment, and nothing has waited over 24 h.
5. **In every case:** at most one High-tier lane. Once more than two lanes are open, every lane beyond the second is Low or Medium and shares no planned file with any other open lane. Step 3's rule is stricter on purpose: it serializes any two lanes that share a file, whatever their number.

Anything beyond that is an override. The user grants it by choosing an option in Step 4 that names the rule it breaks. Report it; never apply it silently.

## 2. Candidates (read-only)

`gh issue list --label ready-for-agent --state open --limit 100 --json number,title,labels,body`. For each issue:

- **Blocked:** an issue its `## Blocked by` section names as a blocker is still open. Read the section, don't regex it: "None. Related: #274" blocks nothing. A blocker that is still open even though its PR merged is probably stale itself. Show it as "blocked by #n (PR merged?)" and let the user decide.
- **In flight:** an open PR or a worktree branch already carries `/<n>-`.
- **Stale or duplicate:** read the cited code on `origin/main` (`git show origin/main:<path>`), and search merged PRs and other issues for the same symptom. If the fix is already on main, or another issue covers it, mark it. Closing or commenting is outward-facing: propose it in Step 4, don't do it.

## 3. Tier, files, overlap, order (read-only)

- **Predicted files:** paths the issue names, plus `git grep` on `origin/main` for the symbols it names, plus the test file the lane will add. A High-tier lane also gets `CONTEXT.md` and `docs/decisions/INDEX.md`, because the grill writes them. Say how confident each prediction is.
- **Tier:** classify the predicted paths with the §1 table. The highest tier among them wins. If the change is in a High category (PHI boundary, cohort or phenotype semantics, auth/RBAC/audit, encryption, IRB scope, golden fixtures) but touches no file on §1's path list, mark it "High?" and let the user decide in Step 4. Don't settle that silently either way.
- **Overlap:** compare predicted files pairwise, and against in-flight work (`gh pr view <n> --json files`, `git diff --name-only origin/main...<branch>`). Run these in series rather than in parallel:
  - two lanes that share a file;
  - two lanes that both touch `tests/conftest.py`, `app/main.py`, `config/**`, `CLAUDE.md`, `CONTEXT.md`, `BACKLOG.md` or `docs/decisions/INDEX.md`;
  - two lanes that change the same behavior from different files, such as a code change and a test asserting the old behavior.
- **Model and effort:** read each candidate's model and effort level from the Model, effort column of §1's table, for the tier set above. Don't restate the table here.
- **Order:** `priority:high` first, then issues that unblock others, then Low and Medium before High. Run at most one High-tier lane at a time, because it starts with the user's design time.

## 4. Present, then ask (the gate)

Show:

- the guardrail table: each Step 1 check, its value, and holds or broken (with the Stage-2 clauses as their own rows when a second lane is on the table);
- the candidate table:

  | # | Tier (paths) | Model, effort | Predicted files | Blocked / overlap | Verdict |
  |---|---|---|---|---|---|
  | A | High (`app/services/feasibility_service.py`) | from §1 | that file, `config/docker-compose.yml`, its test, `CONTEXT.md`, `docs/decisions/INDEX.md` | none | launch, `/grill-with-docs` first |
  | B | Medium (`app/web_ui/research_notebook.py`) | from §1 | that file, a new test | none | next: alone now, or beside a lane already mid-run if the Stage-2 trigger holds (A's grill isn't autonomous, so it doesn't count) |
  | C | High | from §1 | `app/services/feasibility_service.py`, … | shares a file with A | after A |
  | D | High? (auth, outside `app/security/**`) | from §1 once decided | `app/api/auth.py`, … | none | your call on the tier |

- a draft brief for each proposed lane, with its model and effort level, filled from [BRIEF.md](BRIEF.md).

Then use `AskUserQuestion`. It takes 2–4 options per question and up to 4 questions:

1. "Which lanes should start?" (multiSelect): the proposed lanes, no more than the allowed count, plus "None". List the other candidates in text; the user can name one under "Other", which counts as an override when it goes past the cap. If the allowed count is 0, skip this question; question 2's overrides cover it.
2. If a guardrail blocks something the user may want, ask one override question per broken rule, each naming its rule.
3. Ask about stale or duplicate issues, and about worktrees to clean up (their removal and any branch deletion).
4. Ask about "High?" tier calls.

Nothing launches without the user's pick.

## 5. Launch

Start one session per approved lane, each in its own worktree, with a fresh context and its brief as the first message.
- **Desktop app:** use the session tool with a worktree, and pass its `model` and `effort` inputs from Step 3. The lane switches to its own `feat|fix/<n>-<slug>` branch from `origin/main` and sets up its own `.venv` (see the brief).
- **Terminal:** run `scripts/lane.sh open <n> --type <feat|fix> --slug <slug>`, which syncs deps and copies `.env`. Then start `claude --model <id> --effort <level>` in that folder with the brief.

Never launch a lane without both settings: it would inherit this session's. Never run a lane as a subagent of this session. Lanes outlive this turn, the user has to be able to talk to them (a High-tier lane grills the user), and each lane spawns its own reviewer.

## 6. Watch merges

Lanes run `/validate-and-ship` to its end. A standing-rule PR self-merges in its lane. A human-merge PR stops with a ready-to-run command for the user.
- **This session never merges.** Standing-rule PRs merge in their own lane, and human-merge PRs are the user's. This session never runs `gh pr merge`, never posts an attestation, and never reviews a lane's code. Merges use the command validate-and-ship hands over.
- **A PR that's out of date:** when the user wants to merge it, message its lane (or ask the user to relay) to update under validate-and-ship Step 7.4, re-run the Step 8 checks, and hand over a fresh command. Don't update every open PR after each merge; only the next one to merge.
- **Before the user runs a lane's merge command,** offer a read-only sanity check:
  - validate-and-ship Step 8's two all-green commands on the PR's head;
  - that the repo owner's newest attestation names the head, and its verdict: run the reader in validate-and-ship Step 7.5 on the PR and read its `NEWEST` line. `STALE`, `MISSING`, an `EDITED` line or a `BLOCK` verdict never clears it; anything else, validate-and-ship Step 8 decides. Tell the user about each `IGNORED` line, an attestation that another account posted. If `carried-from` isn't `none`, that attestation is a carry-forward; the lane's Step 8 verifies its root, and this check doesn't.
  - the pipeline section of `preflight.sh`.
- **Merge order:** if several PRs are ready, suggest `priority:high` (from the linked issue) first, then the oldest.
- **After every merge you see, whether a lane's or the user's,** wait for main's push runs on the new `origin/main` commit (validate-and-ship Step 8's `until` loop with that SHA), then re-run `preflight.sh` and read the protection and pipeline sections.
  - `MAIN OK` and protection `true`: carry on.
  - Anything red: launch nothing beyond the one fix lane Step 1 allows, and tell the user which run failed and which PR just merged. Offer to ask the other lanes to hold their merges until the user chooses between a fix forward and a revert. Only the user can call a hold: send it with the user's OK (SendMessage in the desktop app; in a terminal, the user relays it).
  - Protection no longer `true`: tell the user. The cap drops to 2 (Step 1).
  - A revert trigger in override health: tell the user, and the cap is 2 until they decide (Step 1).

## 7. Lane close

The lane runs validate-and-ship Step 9, which writes back any correction. Tell the user the lane's model and effort level and how far the plan limits moved since launch, said in the chat and not written to a committed file. Cleanup is the user's call:
- **Lanes `lane.sh` created:** `scripts/lane.sh close <n> --delete-branch`.
- **Lanes it didn't create** (desktop `.claude/worktrees/…`, scratchpad worktrees): `git worktree remove <path>`, once the worktree is clean and its PR is merged. `lane.sh close` only prints "no worktree dir" and prunes for these, because it looks for `<repo>-<n>`.
- **Branches:** a squash-merged branch needs `git branch -D`, and deleting a branch is the user's call.
- **App sessions:** archiving one can leave its worktree on disk, so check `git worktree list` afterwards.

Re-run Step 1 before launching a replacement lane.
