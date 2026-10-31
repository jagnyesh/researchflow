#!/bin/bash
# dials.sh — the two §10 throughput dials, computed from merged PRs:
#   open→green  (PR created → last pre-merge check green) = pipeline health
#   green→merge (last check green → merge)                = human latency
# and flags PRs merged while a check was still running (merged-before-all-green)
# or had already failed (merged-on-red).
# Grouped by merge day (session proxy — this repo's cadence is per-session,
# not per-calendar-week). Usage: dials.sh [limit]   (default 30; the
# statusCheckRollup field makes the API call heavy, keep the limit modest)
set -euo pipefail
limit="${1:-30}"

gh pr list --state merged --limit "$limit" \
  --json number,title,createdAt,mergedAt,statusCheckRollup |
jq -r '
  def ts: sub("\\.[0-9]+"; "") | fromdate;
  def brief: length as $k | .[:3] + (if $k > 3 then ["+\($k - 3) more"] else [] end) | join(", ");
  map(. as $pr
    # last SUCCESS check completed inside the PR window: post-merge completions
    # (standalone CodeQL) would make green->merge negative; pre-creation ones
    # (push-triggered runs on feature/** before the PR opened) make open->green
    # negative — both fall through to merged-before-green
    | ([.statusCheckRollup[]?
        | select((.conclusion? == "SUCCESS") and (.completedAt? != null)
                 and (.completedAt <= $pr.mergedAt)
                 and (.completedAt >= $pr.createdAt))
        | .completedAt] | max) as $green
    # checks still running at merge (the merge rule is all-green): completed
    # after it, or never — gh renders an unset completedAt as the zero time. A
    # StatusContext has no completedAt; its startedAt is when its current state
    # was posted. The code-scanning "CodeQL" run has no workflow; it completes
    # inside its codeql-analysis job, which is counted.
    | ([.statusCheckRollup[]?
        | select((.workflowName // "") != "" or .name != "CodeQL")
        | select(if .__typename == "StatusContext"
                 then .state == "PENDING" or .state == "EXPECTED" or .startedAt > $pr.mergedAt
                 else (.completedAt // "") as $c
                      | $c == "" or ($c | startswith("0001-")) or $c > $pr.mergedAt end)
        | .name // .context] | unique) as $pending
    # checks already failed at merge, including ones that failed before the PR
    # opened (a push-triggered run on the head commit is still red at merge).
    # The code-scanning "CodeQL" run counts here, unlike above: it fails on new
    # alerts while its codeql-analysis job passes (#38). The rollup keeps only
    # the latest attempt of each check, so a failure re-run green before the
    # merge was green at merge and is not flagged; one re-run after it, whatever
    # the result, reads as merged-before-all-green.
    | ([.statusCheckRollup[]?
        | select(if .__typename == "StatusContext"
                 then (.state | IN("FAILURE", "ERROR")) and .startedAt <= $pr.mergedAt
                 else (.conclusion | IN("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"))
                      and .completedAt <= $pr.mergedAt end)
        | .name // .context] | unique) as $failed
    | {day: (.mergedAt | ts | strftime("%Y-%m-%d")), n: .number, t: .title,
       og: (if $green then ((($green|ts) - (.createdAt|ts))/60 | round) else null end),
       gm: (if $green then (((.mergedAt|ts) - ($green|ts))/60 | round) else null end),
       early: (($pending | length) as $k | if $k == 0 then "" else
         "merged-before-all-green (\($k) check\(if $k > 1 then "s" else "" end) pending: \($pending | brief))  " end),
       red: (($failed | length) as $k | if $k == 0 then "" else
         "merged-on-red (\($k) failed: \($failed | brief))  " end)})
  | group_by(.day) | reverse | .[]
  | "== \(.[0].day)  (\(length) merged) ==",
    (.[] | if .og == null
      then "  #\(.n)  merged-before-green (no completed pre-merge check)  \(.red)\(.early)\(.t[0:56])"
      else "  #\(.n)  open->green \(.og)m   green->merge \(.gm)m   \(.red)\(.early)\(.t[0:56])" end),
    ([.[].gm | select(. != null)] | sort
     | if length > 0 then "  median green->merge: \(.[length/2|floor])m" else empty end),  # upper-median on even counts
    "  merged-before-all-green: \(map(select(.early != "")) | length) of \(length)",
    "  merged-on-red: \(map(select(.red != "")) | length) of \(length)"
'
