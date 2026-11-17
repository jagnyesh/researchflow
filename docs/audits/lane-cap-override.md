# Lane-cap override log

This log backs the lane-cap override in `docs/DAILY_DEV_WORKFLOW.md` §3, which raised the lane cap from 2 to 4. The override landed on `main` at 2026-11-07 22:38:02 UTC in [#379](https://github.com/jagnyesh/researchflow/pull/379). §3 asks the log to hold three things:

- each merged PR's wait;
- the failed push runs on `main`, with any attribution;
- `scripts/dials.sh` output.

A PR's wait is §3's "waiting on you". It runs from the PR's first attestation comment with a `SHIP` or `SHIP-WITH-FIXES` verdict until the PR merges. All times are UTC. The tables below were refreshed on 2026-11-15 at about 04:45, against `main` at `71e8b36`.

## Waits of the PRs merged under the override

`.claude/skills/plan-lanes/preflight.sh` computes these waits. Of the 65 PRs merged since the override landed, three waited over 24 h: #396, #460 and #463. Each is a revert trigger under §3's first bullet, and the decisions on them are below.

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
| [#500](https://github.com/jagnyesh/researchflow/pull/500) | 2026-11-14 22:13 | 3 min |
| [#502](https://github.com/jagnyesh/researchflow/pull/502) | 2026-11-14 22:19 | 5 min |
| [#501](https://github.com/jagnyesh/researchflow/pull/501) | 2026-11-14 22:24 | 13 min |
| [#505](https://github.com/jagnyesh/researchflow/pull/505) | 2026-11-14 22:42 | 23 min |
| [#506](https://github.com/jagnyesh/researchflow/pull/506) | 2026-11-15 00:34 | 127 min |
| [#507](https://github.com/jagnyesh/researchflow/pull/507) | 2026-11-15 00:56 | 149 min |
| [#508](https://github.com/jagnyesh/researchflow/pull/508) | 2026-11-15 01:19 | 3 min |
| [#514](https://github.com/jagnyesh/researchflow/pull/514) | 2026-11-15 01:25 | 4 min |
| [#510](https://github.com/jagnyesh/researchflow/pull/510) | 2026-11-15 01:35 | 18 min |
| [#509](https://github.com/jagnyesh/researchflow/pull/509) | 2026-11-15 01:43 | 27 min |
| [#511](https://github.com/jagnyesh/researchflow/pull/511) | 2026-11-15 01:52 | 35 min |
| [#512](https://github.com/jagnyesh/researchflow/pull/512) | 2026-11-15 02:02 | 43 min |
| [#513](https://github.com/jagnyesh/researchflow/pull/513) | 2026-11-15 02:09 | 50 min |
| [#518](https://github.com/jagnyesh/researchflow/pull/518) | 2026-11-15 04:18 | 132 min |
| [#516](https://github.com/jagnyesh/researchflow/pull/516) | 2026-11-15 04:31 | 184 min |

## Failed push runs on main

Two push runs on `main` have failed since the override landed. Under §3, a failed push run that the owner attributes to something outside the merged PRs is not a revert trigger.

| Run | Commit | Created | Attribution |
|---|---|---|---|
| Tests [42865240599](https://github.com/jagnyesh/researchflow/actions/runs/42865240599) | `3759f90`, the merge of #426 | 2026-11-10 17:28 | Runner outage, attributed by the owner on 2026-11-11 (issue #410) |
| Tests [43081612752](https://github.com/jagnyesh/researchflow/actions/runs/43081612752) | `bff1649`, the merge of #448 | 2026-11-11 18:50 | Runner outage, attributed by the owner on 2026-11-14 |

On both runs the `test (macos-latest, 3.11)` job was cancelled after 15 minutes with no runner assigned, and `security-scan` was skipped because it depends on the test jobs. The `test (ubuntu-latest, 3.11)` and `service-dependent-tests` jobs passed. Neither run was re-run: both show attempt 1.

For the `3759f90` run, the two pushes to `main` that followed, `29491c0` (#429) and `e9cd119` (#398), both passed Tests on their first attempt, macOS job included. Neither changes a file under `.github/`.

## dials.sh output

`scripts/dials.sh 75`, run 2026-11-15. The limit of 75 covers all 65 override-era merges plus older ones. #371, #373 and #379 and the other 2026-11-07 merges before 22:38 landed before the override took effect. dials.sh's green→merge clock restarts whenever a branch is updated from `main`, so it understates the waits above. For example, it shows 42 min for #396 against a wait of 2,732 min.

```
== 2026-11-15  (11 merged) ==
  #518  open->green 9m   green->merge 125m   fix: formal SQL generator fails or builds the meant coho
  #516  open->green 178m   green->merge 7m   fix: the phenotype SQL reject route is the reviewer's ch
  #514  open->green 4m   green->merge 1m   fix: notebook "proceed" submits the formal request with
  #513  open->green 51m   green->merge 0m   fix: Synthea loader takes its bundle directory from an a
  #512  open->green 43m   green->merge 1m   fix: e2e extraction test no longer sets HEALTHCARE_DB_UR
  #511  open->green 35m   green->merge 1m   fix: refresh script exits 1 and logs real counts when vi
  #510  open->green 19m   green->merge 0m   docs: fix dead links and stale claims in docs/README.md
  #509  open->green 26m   green->merge 2m   docs: Merge actor rule says only the owner's unedited at
  #508  open->green 3m   green->merge 1m   docs: §3 Waiting on you starts at the repo owner's attes
  #507  open->green 137m   green->merge 13m   fix: attestation workflow step calls set-status, which r
  #506  open->green 20m   green->merge 108m   fix: POST /mcp/context answers an unsafe request_id with
  median green->merge: 1m
  merged-before-all-green: 0 of 11
  merged-on-red: 0 of 11
== 2026-11-14  (15 merged) ==
  #505  open->green 10m   green->merge 13m   fix: security-check follow-ups from the #493 review (#49
  #502  open->green 4m   green->merge 2m   fix: extraction writes every CSV or fails, never a parti
  #501  open->green 14m   green->merge 0m   fix: attestation.sh set-status retries transient 5xx on
  #500  open->green 3m   green->merge 0m   docs: lane-cap override log records the keep-4 decisions
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
  merged-before-all-green: 0 of 15
  merged-on-red: 1 of 15
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

## 2026-11-15: nine lanes opened at once, for one round

**Decision.** On 2026-11-15 at 01:11 you chose to open nine lanes at once. You had asked for ten, and the session planning lanes found nine ready issues that shared no planned file. Your choice set aside two of §3's conditions for this round only: the cap of 4, and Stage 2's trigger for every lane beyond the first. §3 still says 4. It calls going past 4 "a separate decision", and this entry records that decision for one round, not a new cap.

§3's other conditions held when the lanes opened. No PR was open, `main` was green, and strict protection was on. One lane was High tier, the lane for #456. The other eight were Low or Medium.

In the same answer you decided that #499, #503 and #504 are not escapes, which are §3's third revert trigger. You read them as scope splits: work split out of an issue on purpose, not bugs filed against a merged PR. #499 was split out of #477 before [#502](https://github.com/jagnyesh/researchflow/pull/502), the PR for #477, opened. #503 and #504 were filed during the review of #502. All three cover gaps that [ADR 0038](../decisions/0038-extraction-writes-every-csv-or-fails.md) leaves open.

**What the round did.** The nine lanes opened at 01:15. Their PRs are #508–#514, #516 and #518 in the table above. Seven had merged by 02:09, and the last merged at 04:31.

- The waits ran from 3 to 184 minutes, so none met the first trigger.
- Each of the nine merge commits passed Tests, Security Scanning and Documentation on `main` at its first attempt.
- No PR was reverted, and none of the nine closed issues has reopened.
- Two issues were filed during the round, [#515](https://github.com/jagnyesh/researchflow/issues/515) and [#517](https://github.com/jagnyesh/researchflow/issues/517). #515 came from the review of the change in #516, and #517 from the review of the change in #518. On 2026-11-15 you decided that neither is an escape.
  - #515 reports a bug that the review found outside the diff, in code that predates the override.
  - #517 is a scope split of #456. It proposes an allowlist in place of the word denylist that #518 added. It also lists inputs that still build the wrong cohort after #518, such as a gender of `!= male`. #518's review routed those inputs to #517 before #518 merged. Before #518 the gender clause had no negation check, so `!= male` already built the male cohort.

**Analysis (the coordinating session's reading, not your stated reason).** No wait came near the 24 h bar. The round's cost was the updates that each merge forced on the other open PRs.

- Eight of the nine PRs got their first attestation between 01:15 and 01:27. Under strict protection, each merge left every other open PR behind `main`. After their first attestations, the nine PRs took 15 updates from `main` and 13 carried-forward attestations, across seven PRs.
- Six of those updates were made through GitHub while the PR's attestation still named its earlier head. Five came between 01:20 and 01:25, on #509–#513. Each PR then waited for its lane to carry the attestation forward under validate-and-ship Step 7.4. #510's first verdict was `SHIP-WITH-FIXES`, which Step 7.4 can't carry, so #510 needed a second review.
- #516 waited longest, and its wait has the cause the #396 entry gives. #516 was up to date and green from 01:30 until #510 merged at 01:35. It was then behind `main` until 04:21. Four more PRs merged by 02:09, about 8 to 9 minutes apart. Each had auto-merge on, so after its lane's update it merged without a further step from you. #516 had no auto-merge, so after an update it also needed your merge. The coordinating session took no turn between 02:06 and 04:21, so it did not ask #516's lane to update. #516 was updated through GitHub at 04:21 and merged at 04:31.
- #518 was green and attested from 02:14, and you merged it at 04:18. No other PR merged between those times, so those 124 minutes don't come from the lane count.

## Logged week

§3 makes the first 7 days after the override landed the logged week that Stage 2's exit asks for. That week runs from 2026-11-07 22:38 to 2026-11-14 22:38. Two of its conditions hold:

- 53 PRs merged in the week;
- #395, #396 and #397 were open together from 2026-11-08 03:23, so 3 lanes ran at once that day.

On 2026-11-10, after the decision, four lanes were open at once: #284, #329, #387 (PR #406) and #403.

Stage 2's exit also needs a week in which no PR waited on you more than a day. #396, #460 and #463 each waited longer than that, so this week can't meet the exit.

## 2026-11-16: the cap is removed, and this log ends

On 2026-11-16 the owner removed the lane cap. The issue is [#522](https://github.com/jagnyesh/researchflow/issues/522); `docs/DAILY_DEV_WORKFLOW.md` §3 records the decision.

**Why.** The cap limited lanes in flight, not what feeds them. Between 2026-11-01 and 2026-11-16, 152 issues were opened, and by a regex count 87 of them cite another issue or PR together with review or follow-up wording. The queue stayed level at every lane count. The first revert trigger also fired three times (#396, #460 and #463), and each time the cap stayed at 4, so the rule no longer described practice.

**What replaces it.** Three rules in §3 still stop a launch. §10's dials show the load at the launch gate, and the owner decides from them. The dials include two issue-flow measures from `scripts/review_metrics.py`: follow-ups filed per merged PR, and issues opened against closed per week.

**What it accepts.** Green PRs waiting on a human merge can pile up faster than under the cap. The dials show that pile; they don't limit it.

The override's revert triggers, the logged-week test and this log's per-merge records no longer apply, and nothing appends to this file after this entry.
