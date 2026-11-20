---
name: plan-lanes
description: Plans and launches issue lanes for this repo. Checks the §3 launch rules (branch protection, main green, file overlap), shows the §10 dials, verifies and risk-tiers the open ready-for-agent issues, predicts each one's files and finds overlap, drafts lane briefs, and after the user approves starts one worktree session per issue (/tdd then /validate-and-ship; High tier starts with /grill-with-docs). It then watches main after each merge and stops launching when main goes red. Use when the user wants to work through the ready-for-agent queue, start the next issue or two, or plan lanes.
disable-model-invocation: true
---

# plan-lanes

Run this skill in a fresh session on Opus at medium effort (`docs/DAILY_DEV_WORKFLOW.md` §1). Lanes inherit this session's model and effort unless Step 5 sets them.

Plan, ask, launch, watch. Launching is cheap and reversible: each lane is its own branch in its own folder. Merging is where separate changes first meet. This skill adds no merge rule of its own:
- lanes ship through `/validate-and-ship` unchanged;
- `main`'s "require branches to be up to date" protection forces every PR to pass its required checks on the latest main before it can merge, so merges serialize;
- this session's job at merge time is to check and report.

Required checks don't cover everything: Container Security Scan and `test (macos-latest, 3.11)` run only on push to main (#462). The code-scanning `CodeQL` check and the `codeql-analysis (python)` job are both required (#469), so a red `CodeQL` means the PR added an alert; fix it, don't treat it as advisory. So main can still go red after a merge, which is why Step 6 watches it.

Authorities, by reference: risk tiers `docs/DAILY_DEV_WORKFLOW.md` §1, the launch rules §3, the dials §10, attestation templates and merge rules `.claude/skills/validate-and-ship/SKILL.md` Steps 7–8.

## 1. Pre-flight (read-only)

Run `.claude/skills/plan-lanes/preflight.sh`. It runs git and gh queries only, and the one local change is fetching `origin/main`. A nonzero exit or any `ERROR:` line means the report is incomplete: fix the cause or tell the user, and don't plan on a blank section. Then read its sections:

1. **Protection:** must print `true`. Otherwise §3 applies. Say why.
2. **Pipeline:** `MAIN OK`, or the runs that aren't green. If a run is queued or in progress, wait and re-run; don't plan on an unknown main. The 7-day list shows push runs that failed, or that passed only on a re-run. Treat main as flaky if a run passed with `attempt` > 1, or if a workflow failed and then passed on a later commit that didn't fix it. A re-run that failed again is a real failure, not a flake.
3. **Open PRs:**
   - **Green PRs awaiting merge:** the green, non-draft ones, each waiting on your merge, plus any lane waiting on your answer. A dial (§10).
   - **Wait:** every non-draft open PR, green or not, shows how long it has waited on you since its first `SHIP` attestation. That's §3's definition; dials.sh's green→merge restarts on every update from main. `OVER 24h` marks a long one; it's information, not a gate.
4. **Merges in the last 7 days:** how many merged, which of them waited over 24 h, and any merged without a SHIP attestation (its wait can't be measured and it may be a merge-policy breach, so ask the user). Information for the gate, not a gate. The failed push runs on main are in the pipeline section (item 2), and they feed §3's first rule.
5. **Active lanes:** every worktree other than the main checkout whose PR isn't merged or closed, a lane with no commits yet included, plus cloud sessions. `scripts/lane.sh status` reports a count of the `feat/<n>-` and `fix/<n>-` ones; it doesn't see other branch names or cloud sessions. A worktree counts as an active lane unless:
   - its PR is `MERGED` or `CLOSED`;
   - it's marked `this-checkout` with 0 commits ahead and no open PR (the checkout you're planning from; run the skill from the main checkout when you can);
   - it's detached with 0 commits ahead, or `prunable`. This exemption is the skill's own reading: such a checkout has no branch or no folder, so it can't be a lane.

   A branch with 0 commits ahead and no PR counts unless the user says it's a scratch checkout. A branch with commits ahead and no PR is live, unreviewed work, and it counts. Ask the user about cloud sessions and any other lane with no local worktree. Merged or closed lanes are cleanup candidates for Step 4. Note how many active lanes are High tier (a dial).
6. **Plan limits:** the account's plan limits, read from the app's usage report when the session has one, otherwise "not available". Show the row at the gate; the owner decides whether to launch. Don't write the figures into any committed file.
7. **Queue:** the ready-for-agent count.
8. **Issue flow:** run `scripts/review_metrics.py --summary` and read its two blocks: follow-ups filed per merged PR, by tier, and issues opened against closed per week. It reads GitHub and rewrites `logs/review_metrics.csv`, which git ignores. A dial (§10).

**What stops a launch.** Only §3's rules do. Apply them to the pipeline and protection sections above and to Step 3's overlap check, and say which holds or breaks. Everything else in this step is a dial: show it at the gate (Step 4) and leave the call to the user. Never turn a dial into a refusal on your own.

## 2. Candidates (read-only)

`gh issue list --label ready-for-agent --state open --limit 100 --json number,title,labels,body`. For each issue:

- **Blocked:** an issue its `## Blocked by` section names as a blocker is still open. Read the section, don't regex it: "None. Related: #274" blocks nothing. A blocker that is still open even though its PR merged is probably stale itself. Show it as "blocked by #n (PR merged?)" and let the user decide.
- **In flight:** an open PR or a worktree branch already carries `/<n>-`.
- **Stale or duplicate:** read the cited code on `origin/main` (`git show origin/main:<path>`), and search merged PRs and other issues for the same symptom. If the fix is already on main, or another issue covers it, mark it. Closing or commenting is outward-facing: propose it in Step 4, don't do it.

## 3. Tier, files, overlap, order (read-only)

- **Predicted files:** paths the issue names, plus `git grep` on `origin/main` for the symbols it names, plus the test file the lane will add. A High-tier lane also gets `CONTEXT.md` and `docs/decisions/INDEX.md`, because the grill writes them. Say how confident each prediction is.
- **Tier:** classify the predicted paths with the §1 table. The highest tier among them wins. If the change is in a High category (PHI boundary, cohort or phenotype semantics, auth/RBAC/audit, encryption, IRB scope, golden fixtures) but touches no file on §1's path list, mark it "High?" and let the user decide in Step 4. Don't settle that silently either way.
- **Overlap:** compare predicted files pairwise, and against in-flight work (`gh pr view <n> --json files`, `git diff --name-only origin/main...<branch>`). §3 says which overlaps run in series; apply it to every pair.
- **Model and effort:** read each candidate's model and effort level from the Model, effort column of §1's table, for the tier set above. Don't restate the table here.
- **Order:** `priority:high` first, then issues that unblock others, then Low and Medium before High. A High-tier lane starts with the user's design time, so the number open is a dial.

## 4. Present, then ask (the gate)

Show:

- the §3 rules table (each rule, holds or broken), then the dials: green PRs awaiting merge, the longest wait, High-tier lanes open, plan limits, and issue flow (Step 1's item 8);
- the candidate table:

  | # | Tier (paths) | Model, effort | Predicted files | Blocked / overlap | Verdict |
  |---|---|---|---|---|---|
  | A | High (`app/services/feasibility_service.py`) | from §1 | that file, `config/docker-compose.yml`, its test, `CONTEXT.md`, `docs/decisions/INDEX.md` | none | launch, `/grill-with-docs` first |
  | B | Medium (`app/web_ui/research_notebook.py`) | from §1 | that file, a new test | none | launch: shares no file with A |
  | C | High | from §1 | `app/services/feasibility_service.py`, … | shares a file with A | after A |
  | D | High? (auth, outside `app/security/**`) | from §1 once decided | `app/api/auth.py`, … | none | your call on the tier |

- a draft brief for each proposed lane, with its model and effort level, filled from [BRIEF.md](BRIEF.md).

Then use `AskUserQuestion`. It takes 2–4 options per question and up to 4 questions:

1. "Which lanes should start?" (multiSelect): every unblocked candidate that shares no file with another, plus "None". List the rest in text with the reason; the user can name one under "Other". If a §3 rule blocks everything, skip this question; question 2 covers it.
2. If a §3 rule blocks something the user may want, ask one question per broken rule, each naming its rule.
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
  - that the repo owner's newest attestation names the head, and its verdict: run `scripts/attestation.sh read <n>` (the Step 7.5 reader) on the PR and read its `NEWEST` line; the PR's `attestation` status (validate-and-ship Step 7.6) is the same decision, set by CI. `STALE`, `MISSING`, an `EDITED` line or a `BLOCK` verdict never clears it; anything else, validate-and-ship Step 8 decides. Tell the user about each `IGNORED` line, an attestation that another account posted. If `carried-from` isn't `none`, that attestation is a carry-forward; the lane's Step 8 verifies its root, and this check doesn't.
  - the pipeline section of `preflight.sh`.
- **Merge order:** if several PRs are ready, suggest `priority:high` (from the linked issue) first, then the oldest.
- **After every merge you see, whether a lane's or the user's,** wait for main's push runs on the new `origin/main` commit (validate-and-ship Step 8's `until` loop with that SHA, plus `--event push`, the filter `preflight.sh`'s pipeline section uses: comment-triggered `Attestation` runs attach to main's head and can end `cancelled`), then re-run `preflight.sh` and read the protection and pipeline sections.
  - `MAIN OK` and protection `true`: carry on.
  - Anything red: launch nothing beyond the one fix lane §3 allows, and tell the user which run failed and which PR just merged. Offer to ask the other lanes to hold their merges until the user chooses between a fix forward and a revert. Only the user can call a hold: send it with the user's OK (SendMessage in the desktop app; in a terminal, the user relays it).
  - Protection no longer `true`: tell the user (§3).

## 7. Lane close

The lane runs validate-and-ship Step 9, which writes back any correction. Tell the user the lane's model and effort level and how far the plan limits moved since launch, said in the chat and not written to a committed file. Cleanup is the user's call:
- **Lanes `lane.sh` created:** `scripts/lane.sh close <n> --delete-branch`.
- **Lanes it didn't create** (desktop `.claude/worktrees/…`, scratchpad worktrees): `git worktree remove <path>`, once the worktree is clean and its PR is merged. `lane.sh close` only prints "no worktree dir" and prunes for these, because it looks for `<repo>-<n>`.
- **Branches:** a squash-merged branch needs `git branch -D`, and deleting a branch is the user's call.
- **App sessions:** archiving one can leave its worktree on disk, so check `git worktree list` afterwards.

Re-run Step 1 before launching a replacement lane.
