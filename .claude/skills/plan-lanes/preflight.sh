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
# Waiting on you = first SHIP / SHIP-WITH-FIXES attestation comment -> merge (or now). It doesn't
# restart on an update from main, unlike dials.sh's green->merge. The verdict match also accepts
# the drifted "Verdict: **SHIP**" form and a heading after a preamble, since this measures
# time and doesn't gate a merge. Only the repo owner's comments count (validate-and-ship
# Step 7.5), so a SHIP that anyone else posts can't start the clock early. Unlike Step 7.5,
# an edited comment still counts: an edit keeps createdAt, and dropping one would shorten the wait.
wait_jq='def waited: (.url | split("/")[3]) as $owner | ([.comments[] | select(.author.login == $owner and .authorAssociation == "OWNER" and (.body | test("(?m)^## Review attestation")) and (.body | test("(?m)^-?\\s*Verdict:\\s*\\**SHIP")))] | sort_by(.createdAt) | .[0].createdAt) as $a | if $a == null then null else ((((.mergedAt // (now | todate)) | fromdateiso8601) - ($a | fromdateiso8601)) / 60 | floor) end;'

# `gh pr list` returns at most each PR's first 100 comments (it requests comments(first: 100)
# and doesn't page); `gh pr view` pages through all of them. A PR with exactly 100 comments may
# have more, so re-read just those with `gh pr view`; every other PR keeps the one list call.
pr_list_full() {
  local json n full
  json=$(gh pr list "$@") || return 1
  for n in $(jq -r '.[] | select(.comments | length == 100) | .number' <<<"$json"); do
    full=$(gh pr view "$n" --json url,mergedAt,comments) || return 1
    json=$(jq --argjson n "$n" --argjson f "$full" 'map(if .number == $n then .comments = $f.comments else . end)' <<<"$json") || return 1
  done
  printf '%s\n' "$json"
}

echo "== protection (strict up-to-date)"
if strict=$(gh api "repos/$repo/branches/main/protection" -q '.required_status_checks.strict' 2>/dev/null); then
  echo "$strict"
else
  echo "unknown"; fail protection
fi

echo "== pipeline on origin/main $m (push runs only)"
# issue_comment and workflow_dispatch runs (the Attestation workflow, #484) attach to main's head
# too, and a superseded one ends cancelled; they say nothing about whether main is green (#486).
gh run list --commit "$m" --event push --json name,status,conclusion -q 'if length == 0 then "NO RUNS" else (map(select(.status != "completed" or (.conclusion | IN("success","skipped","neutral") | not)) | "\(.name) \(.status) \(.conclusion)") | if length == 0 then "MAIN OK" else .[] end) end' || fail pipeline

echo "== main push runs since $since that failed, or passed only on a re-run (newest 15)"
gh run list --branch main --event push --created ">=$since" --limit 1000 --json name,headSha,conclusion,attempt,createdAt \
  -q '[.[] | select(.conclusion == "failure" or (.attempt > 1 and .conclusion == "success"))] | if length == 0 then "none" else "\(length) total", (.[0:15][] | "\(.createdAt) \(.headSha[0:9]) \(.name) \(.conclusion) attempt=\(.attempt)") end' || fail "recent runs"

echo "== open non-draft PRs: green or not, and how long each has waited on you"
pr_list_full --state open --json number,url,isDraft,statusCheckRollup,comments | jq -r "$wait_jq"'[.[] | select(.isDraft | not) | {n: .number, w: waited, green: ((.statusCheckRollup | length) > 0 and all(.statusCheckRollup[]; .completedAt != "0001-01-01T00:00:00Z" and ((.conclusion // .state) | IN("SUCCESS","SKIPPED","NEUTRAL"))))}] | "green PRs awaiting merge: \([.[] | select(.green) | .n])", (if length == 0 then "none open" else (.[] | "#\(.n) \(if .green then "green" else "not green" end), " + (if .w == null then "no SHIP attestation yet" elif .w > 1440 then "waited \(.w)m OVER 24h" else "waited \(.w)m" end)) end)' || fail "open PRs"

echo "== merged since $since: how long each waited on you (information, not a gate)"
pr_list_full --state merged --search "merged:>=$since" --limit 500 --json number,url,mergedAt,comments \
  | jq -r "$wait_jq"'[.[] | {n: .number, w: waited}] | "merged: \(length)", ([.[] | select(.w != null and .w > 1440)] | if length == 0 then "waited over 24h: none" else "waited over 24h: " + (map("#\(.n) \(.w)m") | join(", ")) end), ([.[] | select(.w == null)] | if length == 0 then empty else "merged without a SHIP attestation (wait unmeasurable; ask the user): " + (map("#\(.n)") | join(", ")) end)' || fail "merged waits"

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
