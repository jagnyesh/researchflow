#!/bin/bash
# Read-only guardrail report for /plan-lanes Step 1: git and gh queries only. The one local
# change is fetching origin/main. Exits nonzero if any section failed, so a blank section
# can't be mistaken for "nothing there".
set -uo pipefail

rc=0
fail() { echo "ERROR: $1 failed"; rc=1; }

git fetch -q origin main || fail "fetch of origin/main (it may be stale)"
m=$(git rev-parse origin/main) || { echo "ERROR: no origin/main"; exit 1; }
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner) || { echo "ERROR: gh repo view failed"; exit 1; }
since=$(date -u -v-7d +%F 2>/dev/null || date -u -d '7 days ago' +%F)
# The lane-cap override (docs/DAILY_DEV_WORKFLOW.md §3) is in force only while origin/main
# carries both its doc block and lane.sh's WIP_LIMIT=4; a revert changes both. Its start is
# the commit that added the block. If either check fails, the report says the cap is 2.
override_start=""
if git show origin/main:scripts/lane.sh 2>/dev/null | grep -qx 'WIP_LIMIT=4' \
   && git show origin/main:docs/DAILY_DEV_WORKFLOW.md 2>/dev/null | grep -q 'Override, 2026-11-07: up to 4 lanes'; then
  override_start=$(TZ=UTC git log origin/main --date=format-local:%Y-%m-%dT%H:%M:%SZ --format=%cd \
    -S 'Override, 2026-11-07: up to 4 lanes' -- docs/DAILY_DEV_WORKFLOW.md | tail -1)
fi
# Waiting on you = first SHIP / SHIP-WITH-FIXES attestation comment -> merge (or now). It doesn't
# restart on an update from main, unlike dials.sh's green->merge. The verdict match also accepts
# the drifted "Verdict: **SHIP**" form, since this measures time and doesn't gate a merge.
wait_jq='def waited: ([.comments[] | select((.body | test("^## Review attestation")) and (.body | test("(?m)^-?\\s*Verdict:\\s*\\**SHIP")))] | sort_by(.createdAt) | .[0].createdAt) as $a | if $a == null then null else ((((.mergedAt // (now | todate)) | fromdateiso8601) - ($a | fromdateiso8601)) / 60 | floor) end;'

echo "== protection (strict up-to-date)"
gh api "repos/$repo/branches/main/protection" -q '.required_status_checks.strict' 2>/dev/null || echo "unknown"

echo "== pipeline on origin/main $m"
gh run list --commit "$m" --json name,status,conclusion -q 'if length == 0 then "NO RUNS" else (map(select(.status != "completed" or (.conclusion | IN("success","skipped","neutral") | not)) | "\(.name) \(.status) \(.conclusion)") | if length == 0 then "MAIN OK" else .[] end) end' || fail pipeline

echo "== main push runs since $since that failed, or passed only on a re-run (newest 15)"
gh run list --branch main --event push --created ">=$since" --limit 1000 --json name,headSha,conclusion,attempt,createdAt \
  -q '[.[] | select(.conclusion == "failure" or (.attempt > 1 and .conclusion == "success"))] | if length == 0 then "none" else "\(length) total", (.[0:15][] | "\(.createdAt) \(.headSha[0:9]) \(.name) \(.conclusion) attempt=\(.attempt)") end' || fail "recent runs"

echo "== open non-draft PRs: green or not, and how long each has waited on you"
gh pr list --state open --json number,isDraft,statusCheckRollup,comments -q "$wait_jq"'[.[] | select(.isDraft | not) | {n: .number, w: waited, green: ((.statusCheckRollup | length) > 0 and all(.statusCheckRollup[]; .completedAt != "0001-01-01T00:00:00Z" and ((.conclusion // .state) | IN("SUCCESS","SKIPPED","NEUTRAL"))))}] | "review debt (green): \([.[] | select(.green) | .n])", (if length == 0 then "none open" else (.[] | "#\(.n) \(if .green then "green" else "not green" end), " + (if .w == null then "no SHIP attestation yet" elif .w > 1440 then "waited \(.w)m OVER 24h" else "waited \(.w)m" end)) end)' || fail "open PRs"

echo "== override health (revert triggers, §3)"
if [ -z "$override_start" ]; then
  echo "override not on origin/main: the cap is 2"
else
echo "override on main since $override_start; checking every merge since then"
gh pr list --state merged --search "merged:>=${override_start%%T*}" --limit 500 --json number,mergedAt,comments \
  -q "$wait_jq"'[.[] | select(.mergedAt >= "'"$override_start"'") | {n: .number, w: waited}] | "merged: \(length)", ([.[] | select(.w != null and .w > 1440)] | if length == 0 then "waited over 24h: none" else "waited over 24h: " + (map("#\(.n) \(.w)m") | join(", ")) end), ([.[] | select(.w == null)] | if length == 0 then empty else "merged without a SHIP attestation: " + (map("#\(.n)") | join(", ")) end)' || fail "override health (waits)"
gh run list --branch main --event push --created ">=${override_start%%T*}" --limit 1000 --json name,headSha,conclusion,createdAt \
  -q '[.[] | select((.conclusion | IN("failure","timed_out","startup_failure")) and .createdAt >= "'"$override_start"'")] | if length == 0 then "failed push runs: none" else "failed push runs: " + (map("\(.headSha[0:9]) \(.name) \(.conclusion)") | join(", ")) end' || fail "override health (runs)"
reverts=$(git log origin/main --since="$override_start" --grep='^Revert' --format='%h %s' | paste -sd ';' -)
echo "revert commits: ${reverts:-none}"
fi

echo "== worktrees other than the main checkout: path | branch | commits ahead of origin/main | PR | flags"
here=$(git rev-parse --show-toplevel)
first=1 path="" head="" branch="" flags=""
report() {
  [ -n "$path" ] || return 0
  if [ "$first" -eq 1 ]; then first=0; return 0; fi
  local ahead pr="-"
  ahead=$(git rev-list --count "origin/main..$head" 2>/dev/null || echo "?")
  if [ -n "$branch" ]; then
    pr=$(gh pr list --head "$branch" --state all --json number,state,isCrossRepository \
      -q '[.[] | select(.isCrossRepository | not)] | (map(select(.state == "OPEN")) + .) | .[0] | if . == null then "no PR" else "\(.state) #\(.number)" end') \
      || { pr="ERROR"; rc=1; }
  fi
  [ "$path" = "$here" ] && flags="$flags this-checkout"
  echo "$path | ${branch:-(detached)} | $ahead | $pr |${flags:- -}"
}
while IFS= read -r line; do
  case "$line" in
    "worktree "*) path=${line#worktree } ;;
    "HEAD "*) head=${line#HEAD } ;;
    "branch refs/heads/"*) branch=${line#branch refs/heads/} ;;
    locked*) flags="$flags locked" ;;
    prunable*) flags="$flags prunable" ;;
    "") report; path="" head="" branch="" flags="" ;;
  esac
done < <(git worktree list --porcelain; echo)

echo "== ready-for-agent queue"
gh issue list --label ready-for-agent --state open --limit 100 --json number -q length || fail queue

exit "$rc"
