#!/bin/bash
# dials.sh — the two §7 throughput dials, computed from merged PRs:
#   open→green  (PR created → last pre-merge check green) = pipeline health
#   green→merge (last check green → merge)                = human latency
# Grouped by merge day (session proxy — this repo's cadence is per-session,
# not per-calendar-week). Usage: dials.sh [limit]   (default 30; the
# statusCheckRollup field makes the API call heavy, keep the limit modest)
set -euo pipefail
limit="${1:-30}"

gh pr list --state merged --limit "$limit" \
  --json number,title,createdAt,mergedAt,statusCheckRollup |
jq -r '
  def ts: sub("\\.[0-9]+"; "") | fromdate;
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
    | {day: (.mergedAt | ts | strftime("%Y-%m-%d")), n: .number, t: .title,
       og: (if $green then ((($green|ts) - (.createdAt|ts))/60 | round) else null end),
       gm: (if $green then (((.mergedAt|ts) - ($green|ts))/60 | round) else null end)})
  | group_by(.day) | reverse | .[]
  | "== \(.[0].day)  (\(length) merged) ==",
    (.[] | if .og == null
      then "  #\(.n)  merged-before-green (no completed pre-merge check)  \(.t[0:56])"
      else "  #\(.n)  open->green \(.og)m   green->merge \(.gm)m   \(.t[0:56])" end),
    ([.[].gm | select(. != null)] | sort
     | if length > 0 then "  median green->merge: \(.[length/2|floor])m" else empty end)  # upper-median on even counts
'
