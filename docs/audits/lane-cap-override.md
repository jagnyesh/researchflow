# Lane-cap override log

This log backs the lane-cap override in `docs/DAILY_DEV_WORKFLOW.md` §3, which raised the lane cap from 2 to 4. The override landed on `main` at 2026-11-07 22:38:02 UTC in [#379](https://github.com/jagnyesh/researchflow/pull/379). §3 asks the log to hold three things:

- each merged PR's wait;
- the failed push runs on `main`, with any attribution;
- `scripts/dials.sh` output.

A PR's wait is §3's "waiting on you". It runs from the PR's first attestation comment with a `SHIP` or `SHIP-WITH-FIXES` verdict until the PR merges. All times are UTC. The tables below were refreshed on 2026-11-14 at about 22:00, against `main` at `202c56e`.

## Waits of the PRs merged under the override

`.claude/skills/plan-lanes/preflight.sh` computes these waits. Of the 50 PRs merged since the override landed, three waited over 24 h: #396, #460 and #463. Each is a revert trigger under §3's first bullet, and the decisions on them are below.

| PR | Merged | Wait |
|---|---|---|
| [#375](https://github.com/jagnyesh/researchflow/pull/375) | 2026-11-07 23:10 | 117 min |
| [#377](https://github.com/jagnyesh/researchflow/pull/377) | 2026-11-07 23:31 | 119 min |
| [#381](https://github.com/jagnyesh/researchflow/pull/381) | 2026-11-07 23:44 | 3 min |
| [#383](https://github.com/jagnyesh/researchflow/pull/383) | 2026-11-08 00:44 | 10 min |
| [#385](https://github.com/jagnyesh/researchflow/pull/385) | 2026-11-08 02:23 | 6 min |
| [#392](https://github.com/jagnyesh/researchflow/pull/392) | 2026-11-08 03:06 | 8 min |
| [#395](https://github.com/jagnyesh/researchflow/pull/395) | 2026-11-08 17:19 | 840 min |
| [#397](https://github.com/jagnyesh/researchflow/pull/397) | 2026-11-08 17:34 | 850 min |
| [#396](https://github.com/jagnyesh/researchflow/pull/396) | 2026-11-10 00:55 | 2,732 min (45.5 h) |
| [#406](https://github.com/jagnyesh/researchflow/pull/406) | 2026-11-10 03:14 | 3 min |
| [#407](https://github.com/jagnyesh/researchflow/pull/407) | 2026-11-10 03:21 | 5 min |
| [#408](https://github.com/jagnyesh/researchflow/pull/408) | 2026-11-10 03:27 | 9 min |
| [#409](https://github.com/jagnyesh/researchflow/pull/409) | 2026-11-10 03:33 | 15 min |
| [#412](https://github.com/jagnyesh/researchflow/pull/412) | 2026-11-10 04:07 | 4 min |
| [#416](https://github.com/jagnyesh/researchflow/pull/416) | 2026-11-10 04:13 | 5 min |
| [#413](https://github.com/jagnyesh/researchflow/pull/413) | 2026-11-10 04:19 | 16 min |
| [#414](https://github.com/jagnyesh/researchflow/pull/414) | 2026-11-10 04:25 | 20 min |
| [#415](https://github.com/jagnyesh/researchflow/pull/415) | 2026-11-10 04:36 | 30 min |
| [#419](https://github.com/jagnyesh/researchflow/pull/419) | 2026-11-10 04:47 | 3 min |
| [#427](https://github.com/jagnyesh/researchflow/pull/427) | 2026-11-10 13:45 | 26 min |
| [#417](https://github.com/jagnyesh/researchflow/pull/417) | 2026-11-10 15:37 | 675 min |
| [#430](https://github.com/jagnyesh/researchflow/pull/430) | 2026-11-10 16:32 | 49 min |
| [#426](https://github.com/jagnyesh/researchflow/pull/426) | 2026-11-10 17:28 | 249 min |
| [#429](https://github.com/jagnyesh/researchflow/pull/429) | 2026-11-10 18:29 | 170 min |
| [#398](https://github.com/jagnyesh/researchflow/pull/398) | 2026-11-11 16:13 | 84 min |
| [#447](https://github.com/jagnyesh/researchflow/pull/447) | 2026-11-11 18:35 | 10 min |
| [#448](https://github.com/jagnyesh/researchflow/pull/448) | 2026-11-11 18:50 | 20 min |
| [#452](https://github.com/jagnyesh/researchflow/pull/452) | 2026-11-11 18:55 | 11 min |
| [#458](https://github.com/jagnyesh/researchflow/pull/458) | 2026-11-11 19:13 | 4 min |
| [#457](https://github.com/jagnyesh/researchflow/pull/457) | 2026-11-11 19:22 | 13 min |
| [#459](https://github.com/jagnyesh/researchflow/pull/459) | 2026-11-11 19:37 | 25 min |
| [#460](https://github.com/jagnyesh/researchflow/pull/460) | 2026-11-13 21:47 | 3,034 min (50.6 h) |
| [#473](https://github.com/jagnyesh/researchflow/pull/473) | 2026-11-13 22:05 | 8 min |
| [#463](https://github.com/jagnyesh/researchflow/pull/463) | 2026-11-13 22:15 | 3,042 min (50.7 h) |
| [#472](https://github.com/jagnyesh/researchflow/pull/472) | 2026-11-13 22:20 | 31 min |
| [#474](https://github.com/jagnyesh/researchflow/pull/474) | 2026-11-13 22:24 | 23 min |
| [#475](https://github.com/jagnyesh/researchflow/pull/475) | 2026-11-13 22:32 | 7 min |
| [#476](https://github.com/jagnyesh/researchflow/pull/476) | 2026-11-13 22:37 | 3 min |
| [#482](https://github.com/jagnyesh/researchflow/pull/482) | 2026-11-13 23:16 | 5 min |
| [#481](https://github.com/jagnyesh/researchflow/pull/481) | 2026-11-14 01:43 | 157 min |
| [#484](https://github.com/jagnyesh/researchflow/pull/484) | 2026-11-14 16:05 | 1,006 min |
| [#488](https://github.com/jagnyesh/researchflow/pull/488) | 2026-11-14 17:23 | 3 min |
| [#487](https://github.com/jagnyesh/researchflow/pull/487) | 2026-11-14 18:01 | 41 min |
| [#489](https://github.com/jagnyesh/researchflow/pull/489) | 2026-11-14 18:06 | 41 min |
| [#490](https://github.com/jagnyesh/researchflow/pull/490) | 2026-11-14 18:10 | 31 min |
| [#491](https://github.com/jagnyesh/researchflow/pull/491) | 2026-11-14 18:24 | 26 min |
| [#495](https://github.com/jagnyesh/researchflow/pull/495) | 2026-11-14 21:29 | 6 min |
| [#497](https://github.com/jagnyesh/researchflow/pull/497) | 2026-11-14 21:45 | 3 min |
| [#496](https://github.com/jagnyesh/researchflow/pull/496) | 2026-11-14 21:50 | 8 min |
| [#498](https://github.com/jagnyesh/researchflow/pull/498) | 2026-11-14 21:56 | 12 min |

## Failed push runs on main

Two push runs on `main` have failed since the override landed. Under §3, a failed push run that the owner attributes to something outside the merged PRs is not a revert trigger.

| Run | Commit | Created | Attribution |
|---|---|---|---|
| Tests [42865240599](https://github.com/jagnyesh/researchflow/actions/runs/42865240599) | `3759f90`, the merge of #426 | 2026-11-10 17:28 | Runner outage, attributed by the owner on 2026-11-11 (issue #410) |
| Tests [43081612752](https://github.com/jagnyesh/researchflow/actions/runs/43081612752) | `bff1649`, the merge of #448 | 2026-11-11 18:50 | Runner outage, attributed by the owner on 2026-11-14 |

On both runs the `test (macos-latest, 3.11)` job was cancelled after 15 minutes with no runner assigned, and `security-scan` was skipped because it depends on the test jobs. The `test (ubuntu-latest, 3.11)` and `service-dependent-tests` jobs passed. Neither run was re-run: both show attempt 1.

For the `3759f90` run, the two pushes to `main` that followed, `29491c0` (#429) and `e9cd119` (#398), both passed Tests on their first attempt, macOS job included. Neither changes a file under `.github/`.

## dials.sh output

`scripts/dials.sh 60`, run 2026-11-14. The limit of 60 covers all 50 override-era merges plus older ones. #371, #373 and #379 and the other 2026-11-07 merges before 22:38 landed before the override took effect. dials.sh's green→merge clock restarts whenever a branch is updated from `main`, so it understates the waits above. For example, it shows 42 min for #396 against a wait of 2,732 min.

```
== 2026-11-14  (11 merged) ==
  #498  open->green 13m   green->merge 0m   fix: keep FHIR URL credentials out of httpx logs and exc
  #497  open->green 3m   green->merge 0m   fix: delivery skips CSVs already in place and writes the
  #496  open->green 8m   green->merge 0m   fix: preflight pipeline check counts push runs only (#48
  #495  open->green 3m   green->merge 3m   feat: security-check skill reports security state and wh
  #491  open->green 17m   green->merge 9m   docs: CLAUDE.md drops sections the repo already shows (#
  #490  open->green 31m   green->merge 1m   test: pytest coverage for scripts/attestation.sh (#485)
  #489  open->green 41m   green->merge 0m   feat: a second reviewer on Fable for High-tier lanes (#4
  #488  open->green 3m   green->merge 0m   docs: CLAUDE.md stops auto-loading BACKLOG.md and the AD
  #487  open->green 41m   green->merge 0m   docs: plan-lanes records CodeQL as a required check (#46
  #484  open->green 149m   green->merge 858m   merged-on-red (1 failed: attestation)  feat: the review attestation becomes a required status c
  #481  open->green 14m   green->merge 144m   fix: CodeQL alerts under app/ cleared in code; /sql_quer
  median green->merge: 0m
  merged-before-all-green: 0 of 11
  merged-on-red: 1 of 11
== 2026-11-13  (8 merged) ==
  #482  open->green 3m   green->merge 2m   fix: emoji ranges checked as code points, not a regex cl
  #476  open->green 3m   green->merge 1m   feat: a Stop hook runs the tests a lane's change can bre
  #475  open->green 7m   green->merge 1m   merged-on-red (1 failed: attestation)  docs: throwaway for #466 attestation test (do not merge)
  #474  open->green 23m   green->merge 1m   docs: HIPAA Automatic Logoff row claims only what the co
  #473  open->green 3m   green->merge 6m   chore: commit permission rules for irreversible actions
  #472  open->green 31m   green->merge 1m   chore: clear CodeQL alerts under scripts/ and tests/ (#4
  #463  open->green 3041m   green->merge 2m   ci: macOS test job runs on main pushes only; every job g
  #460  open->green 3033m   green->merge 1m   fix: researcher portal reads the state registry for stag
  median green->merge: 1m
  merged-before-all-green: 0 of 8
  merged-on-red: 1 of 8
== 2026-11-11  (7 merged) ==
  #459  open->green 16m   green->merge 10m   merged-on-red (1 failed: CodeQL)  fix: every formal criterion concept becomes SQL or the r
  #458  open->green 4m   green->merge 0m   feat: /plan-lanes sets a model and an effort level for e
  #457  open->green 13m   green->merge 0m   chore: delete dead dashboard_helpers.py and its ignored
  #452  open->green 11m   green->merge 1m   refactor: workflow_states.py declares every request stat
  #448  open->green 14m   green->merge 7m   fix: /analytics/health no longer returns the FHIR base U
  #447  open->green 3m   green->merge 8m   test: cached system prompts stay above their model's cac
  #398  open->green 5034m   green->merge 56m   fix: FHIRClient logs host and scheme without userinfo cr
  median green->merge: 7m
  merged-before-all-green: 0 of 7
  merged-on-red: 1 of 7
== 2026-11-10  (16 merged) ==
  #430  open->green 13m   green->merge 36m   fix: inclusive age phrases give >= and <= in the formal
  #429  open->green 115m   green->merge 56m   fix: admin dashboard says "couldn't check" instead of "n
  #427  open->green 3m   green->merge 24m   docs: CLAUDE.md, CHANGELOG.md, and the docs index drop t
  #426  open->green 249m   green->merge 0m   fix: app/ drops the multi-agent wording, including the R
  #419  open->green 3m   green->merge 1m   docs: README drops the multi-agent framing and matches t
  #417  open->green 645m   green->merge 31m   fix: login verifies a dummy bcrypt hash on unknown email
  #416  open->green 4m   green->merge 2m   fix: build the compose app image from the repo root (#38
  #415  open->green 26m   green->merge 5m   fix: preflight re-reads PRs at the 100-comment cap (#402
  #414  open->green 19m   green->merge 1m   fix: create-views script strips +asyncpg from HAPI_DB_UR
  #413  open->green 16m   green->merge 1m   docs: list the same harness-internal paths in the Merge
  #412  open->green 3m   green->merge 1m   fix: plan-lanes brief stops on an EDITED attestation ins
  #409  open->green 13m   green->merge 3m   fix: approvals queue shows delivery QA summary and filte
  #408  open->green 8m   green->merge 2m   fix: remove the dead /auth/token route so /auth/login is
  #407  open->green 4m   green->merge 1m   fix: age cohorts in the formal SQL generator count livin
  #406  open->green 3m   green->merge 1m   docs: green→merge isn't the human wait under strict prot
  #396  open->green 2691m   green->merge 42m   fix: count only the repo owner's unedited review attesta
  median green->merge: 2m
  merged-before-all-green: 0 of 16
  merged-on-red: 0 of 16
== 2026-11-08  (5 merged) ==
  #397  open->green 847m   green->merge 4m   fix: notebook and LangSmith script stop printing part of
  #395  open->green 4m   green->merge 837m   fix: compose app env matches the store URL names the cod
  #392  open->green 4m   green->merge 4m   fix: agents_involved appends assign a new list so they p
  #385  open->green 3m   green->merge 3m   feat: /plan-lanes skill plans, gates and launches issue
  #383  open->green 3m   green->merge 7m   docs: CLAUDE.md's review-debt rule names the fix-lane ex
  median green->merge: 4m
  merged-before-all-green: 0 of 5
  merged-on-red: 0 of 5
== 2026-11-07  (13 merged) ==
  #381  open->green 3m   green->merge 1m   docs: walkthrough points at the 2026-11-07 lane-cap over
  #379  open->green 6m   green->merge 49m   feat: raise the lane cap to 4 under a dated workflow ove
  #377  open->green 112m   green->merge 7m   fix: repoint the last app and test citations of the dele
  #375  open->green 108m   green->merge 10m   fix: repoint stale lane and DECISIONS.md references left
  #373  open->green 3m   green->merge 1m   docs: point domain.md at docs/decisions and record the l
  #371  open->green 4m   green->merge 61m   fix: carry an attestation forward across a clean merge f
  #370  open->green 3m   green->merge 73m   feat: admin dashboard reads as one product with the port
  #369  open->green 3m   green->merge 76m   feat: formal portal reads as a request form and tracker
  #366  open->green 3m   green->merge 3m   feat: exploratory portal makes the cohort count the focu
  #360  open->green 5m   green->merge 2m   fix: de-identified extracts meet the Safe Harbor floor (
  #359  open->green 3m   green->merge 2m   refactor: drop MultiLLMClient, CalendarAgent and the age
  #358  open->green 3m   green->merge 2m   fix: negate exclusion demographics in phenotype SQL (#31
  #357  open->green 4m   green->merge 2m   fix: approval read routes check that the caller may see
  median green->merge: 3m
  merged-before-all-green: 0 of 13
  merged-on-red: 0 of 13
```

## 2026-11-10: #396 fired a revert trigger, and the cap stays at 4

[#396](https://github.com/jagnyesh/researchflow/pull/396) waited 2,732 minutes, from Sunday 2026-11-08 03:23 to Tuesday 2026-11-10 00:55. That meets §3's first revert trigger, "a PR waits on you more than 24 h before merging".

**Decision.** On 2026-11-10 you kept the cap at 4 and accepted #396's wait as a one-off. You chose "Keep 4, override the revert" in the session planning lanes, and "Keep 4, log why" in the session coordinating them. The triggers still apply to every later merge.

**Analysis (the coordinating session's reading, not your stated reason).** The wait has two parts:

- **14.2 h, from 2026-11-08 03:23 to 17:34.** #395, #396 and #397 became ready within 6 minutes of each other. #395 and #397 merged at 17:19 and 17:34, each after about 14 h.
- **30.6 h, from 2026-11-08 17:34 to 2026-11-10 00:09.** After #397 merged, #396 was behind `main`, and strict protection blocked its merge. At 00:09 its lane merged `main` in and carried the attestation forward under validate-and-ship Step 7.4. #396 merged 46 minutes later.

The part past 24 h came from the update after a merge. At a cap of 2, the second of two ready PRs also falls behind `main` when the first merges. It then waits until someone tells its lane to update, and the coordinating session learns about a merge only when you report it. This reading is wrong if the lane count drove the delay. More ready PRs mean more updates after each merge, and one sitting may not get through them all.

## 2026-11-14: #460 and #463 fired the same trigger, and the cap stays at 4

[#460](https://github.com/jagnyesh/researchflow/pull/460) waited 3,034 minutes and [#463](https://github.com/jagnyesh/researchflow/pull/463) waited 3,042 minutes. Both were attested on 2026-11-11, #460 at 19:13 and #463 at 19:32. They merged on 2026-11-13, at 21:47 and 22:15. Each got a carried-forward attestation comment on 2026-11-13 between 21:42 and 22:10, shortly before its merge.

**Decision.** On 2026-11-14 you kept the cap at 4 and accepted both waits as one-offs, as you did for #396. The triggers still apply to every later merge. This entry records no cause for the waits. Issue [#388](https://github.com/jagnyesh/researchflow/issues/388) asks separately whether waits caused by a red `main` should count toward the trigger, and it is still open.

## Logged week

§3 makes the first 7 days after the override landed the logged week that Stage 2's exit asks for. That week runs from 2026-11-07 22:38 to 2026-11-14 22:38. Two of its conditions hold:

- 50 PRs merged in the week, as of 2026-11-14 22:00;
- #395, #396 and #397 were open together from 2026-11-08 03:23, so 3 lanes ran at once that day.

On 2026-11-10, after the decision, four lanes were open at once: #284, #329, #387 (PR #406) and #403.

Stage 2's exit also needs a week in which no PR waited on you more than a day. #396, #460 and #463 each waited longer than that, so this week can't meet the exit.
