#!/bin/bash
# Read-only security state report for /security-check: git and gh queries only. It fetches
# origin/main and saves one snapshot file in a state directory outside the repo, then prints
# what changed since the previous snapshot. Exits nonzero if any section failed, so a blank
# section can't be mistaken for "nothing there"; a failed run saves no snapshot.
#
#   check.sh                        report and save a snapshot
#   check.sh --record-deep <tool>   record that a deep audit (for example cso) ran today
set -uo pipefail

rc=0
fail() { echo "ERROR: $1 failed"; rc=1; }

git fetch -q origin main || fail "fetch of origin/main (it may be stale)"
m=$(git rev-parse origin/main) || { echo "ERROR: no origin/main"; exit 1; }
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner) || { echo "ERROR: gh repo view failed"; exit 1; }
# The snapshot lists open vulnerabilities and the repo is public, so it lives outside the repo.
state=${SECURITY_CHECK_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/security-check/${repo//\//__}}
mkdir -p "$state" || { echo "ERROR: cannot create $state"; exit 1; }
now=$(date +%s)
deep_days=${SECURITY_CHECK_DEEP_DAYS:-90}
cap=300  # longest commit or file list printed; the rest is counted

if [ "${1:-}" = "--record-deep" ]; then
  { [ $# -eq 2 ] && [ -n "$2" ]; } || { echo "usage: check.sh --record-deep <tool>"; exit 2; }
  [ "$rc" -eq 0 ] || { echo "not recorded: origin/main could not be fetched"; exit 1; }
  echo "$now $(date -u +%F) ${m:0:7} $2" > "$state/deep-run"
  echo "recorded deep audit: $2 on $(date -u +%F) at ${m:0:7}"
  exit 0
fi
[ $# -eq 0 ] || { echo "usage: check.sh [--record-deep <tool>]"; exit 2; }

prev=$(find "$state" -maxdepth 1 -name 'snapshot-*.txt' | sort | tail -1)
prev_sha=""
[ -n "$prev" ] && prev_sha=$(sed -n 's/^# main=//p' "$prev")
new=$(mktemp) && log=$(mktemp) && errf=$(mktemp) || { echo "ERROR: mktemp failed"; exit 1; }
trap 'rm -f "$new" "$log" "$errf"' EXIT

emit() { echo "$1"; echo "$1" >> "$new"; }      # compared with the previous run
note() { echo "# $1"; echo "# $1" >> "$new"; }  # recorded, never compared
emit_lines() { local l; while IFS= read -r l; do [ -n "$l" ] && emit "$l"; done; }
# Emit what a jq filter makes of a JSON document. A jq error fails the section: it must not
# leave the section blank, or the run would save a snapshot with lines missing.
emit_jq() {  # section name, json, jq filter
  local lines
  if lines=$(jq -r "$3" <<<"$2" 2>/dev/null); then emit_lines <<<"$lines"; else fail "$1"; fi
}
# Open alerts from one endpoint, counted by a jq key. Only stdout is counted: gh writes
# debug and warning lines to stderr. "disabled" in the API's error is a state to record.
alerts() {  # name, endpoint, jq key expression
  local out
  if out=$(gh api --paginate "repos/$repo/$2?state=open&per_page=100" -q ".[] | $3" 2>"$errf"); then
    emit "$1.open=$(grep -c . <<<"$out")"
    grep . <<<"$out" | sort | uniq -c | awk -v p="$1" '{print p "." $2 "=" $1}' | emit_lines
  elif grep -qi disabled "$errf"; then
    emit "$1.open=disabled"
  else
    fail "$1 alerts"
  fi
}
# gh gives an unfinished job the conclusion "", not null, so "//" alone never reaches status.
jobs_of() {  # run id, key prefix
  gh run view "$1" --json jobs | jq -r --arg p "$2" '.jobs[]
    | "\($p).\(.name | gsub("[^A-Za-z0-9]+"; "_"))=\(if (.conclusion // "") == "" then .status else .conclusion end)"'
}

echo "== security-check $repo at ${m:0:7} ($(date -u +%FT%TZ))"
note "main=$m"
echo "previous snapshot: ${prev:-none}"

echo "== alerts (open)"
alerts code_scanning code-scanning/alerts \
  '"\(.tool.name | gsub("[^A-Za-z0-9]+"; "_")).\(.rule.security_severity_level // .rule.severity // "none")"'
alerts secret_scanning secret-scanning/alerts '"alert"'
alerts dependabot dependabot/alerts '.security_advisory.severity'

echo "== scans (security-scan.yml, latest completed runs)"
if sched=$(gh run list --workflow security-scan.yml --event schedule --status completed --limit 1 \
    --json databaseId,createdAt,headSha \
    -q '.[0] // empty | "\(.databaseId) \(.createdAt[0:10]) \(.headSha[0:7]) \((now - (.createdAt | fromdateiso8601)) / 86400 | floor)"'); then
  if [ -z "$sched" ]; then
    emit "scan.scheduled=none"
  else
    read -r sid sdate ssha sage <<<"$sched"
    note "scan.scheduled.run=$sid $sdate $ssha (${sage}d ago)"
    # The schedule is weekly, so more than 8 days without a run means it stopped firing.
    if [ "$sage" -gt 8 ]; then emit "scan.scheduled.stale=yes"; else emit "scan.scheduled.stale=no"; fi
    if lines=$(jobs_of "$sid" scan.scheduled); then emit_lines <<<"$lines"; else fail "scheduled scan jobs"; fi
  fi
else
  fail "scheduled scan lookup"
fi
rid=""
if run=$(gh run list --workflow security-scan.yml --branch main --event push --status completed --limit 1 \
    --json databaseId,headSha -q '.[0] // empty | "\(.databaseId) \(.headSha)"') && [ -n "$run" ]; then
  read -r rid rsha <<<"$run"
  [ "$rsha" = "$m" ] || echo "NOTE: the latest completed scan ran on ${rsha:0:7}; main is ${m:0:7}"
  note "scan.main.run=$rid ${rsha:0:7}"
  if lines=$(jobs_of "$rid" scan.main); then emit_lines <<<"$lines"; else fail "main scan jobs"; fi
else
  fail "main scan lookup"
fi

# These steps end in "|| true" in the workflow, so CI is green whatever they find. Their
# results exist only in the log. A missing result line means the pattern or the step changed.
echo "== scanners that cannot fail the build (results from run ${rid:-none})"
if [ -n "$rid" ] && gh run view "$rid" --log > "$log" 2>/dev/null && [ -s "$log" ]; then
  pa=$(grep -m1 -oE 'Found [0-9]+ known vulnerabilit(y|ies) in [0-9]+ packages?|No known vulnerabilities found' "$log")
  if [ -n "$pa" ]; then emit "report.pip_audit=$pa"; else fail "pip-audit result line"; fi
  sf=$(grep -m1 -oE '"vulnerabilities_found": [0-9]+' "$log" | grep -oE '[0-9]+$')
  if [ -n "$sf" ]; then emit "report.safety=$sf"; else fail "safety result line"; fi
  bd=$(awk -F'\t' '/Total issues \(by severity\)/ {f=4; next} f>0 {gsub(/[ \t]/,"",$NF); print $NF; f--}' "$log" | head -4 | paste -sd, -)
  if [ -n "$bd" ]; then emit "report.bandit=$bd"; else fail "bandit result lines"; fi
else
  fail "scan log download"
fi
if wf=$(git show origin/main:.github/workflows/security-scan.yml 2>/dev/null); then
  emit "report.unfailing_steps=$(grep -c '|| true' <<<"$wf")"
else
  fail "security-scan.yml read"
fi

# The digest covers every protection field, so a change the lines above it don't itemize
# still shows. A branch with no protection is a state to record, not a failed query.
echo "== branch protection and repo settings"
if p=$(gh api "repos/$repo/branches/main/protection" 2>"$errf"); then
  emit_jq "branch protection" "$p" '(.required_status_checks // {}) as $c
    | ($c.checks // ($c.contexts // [] | map({context: .}))) as $checks
    | "protection.strict=\($c.strict)",
      "protection.required_count=\($checks | length)",
      "protection.required=\($checks | map("\(.context)\(if .app_id then "@\(.app_id)" else "" end)") | sort | join(","))",
      "protection.enforce_admins=\(.enforce_admins.enabled)",
      "protection.force_pushes=\(.allow_force_pushes.enabled)",
      "protection.deletions=\(.allow_deletions.enabled)",
      "protection.signatures=\(.required_signatures.enabled // false)",
      "protection.required_reviews=\(.required_pull_request_reviews.required_approving_review_count // "none")"'
  if dg=$(jq -S -c . <<<"$p" 2>/dev/null | git hash-object --stdin); then emit "protection.digest=${dg:0:12}"; fi
elif grep -q "Branch not protected" "$errf"; then
  emit "protection=none"
else
  fail "branch protection"
fi
if r=$(gh api "repos/$repo" 2>/dev/null); then
  emit_jq "repo settings" "$r" '"repo.visibility=\(.visibility)", "repo.allow_auto_merge=\(.allow_auto_merge)",
    (.security_and_analysis // {} | to_entries[] | "repo.\(.key)=\(.value.status)")'
else
  fail "repo settings"
fi

# The blob and tree ids cover the whole settings file and every hook script, so a change
# the itemized lines don't show (a hook's command, an ask rule swapped for another) still does.
echo "== harness (.claude/settings.json and .claude/hooks on origin/main)"
if s=$(git show origin/main:.claude/settings.json 2>/dev/null); then
  emit_jq "settings.json read" "$s" '"harness.deny=\(.permissions.deny // [] | sort | join(";"))",
    "harness.allow=\(.permissions.allow // [] | sort | join(";"))",
    "harness.default_mode=\(.permissions.defaultMode // "unset")",
    "harness.ask_count=\(.permissions.ask // [] | length)",
    "harness.hooks=\(.hooks // {} | keys | join(","))"'
  emit "harness.settings_blob=$(git rev-parse --short=12 origin/main:.claude/settings.json)"
  emit "harness.hooks_tree=$(git rev-parse --short=12 --verify -q origin/main:.claude/hooks || echo none)"
else
  fail "settings.json read"
fi

echo "== open priority:high issues"
if out=$(gh issue list --state open --label priority:high --limit 200 --json number,title,createdAt \
    -q 'sort_by(.number) | .[] | "#\(.number) \((now - (.createdAt | fromdateiso8601)) / 86400 | floor)d \(.title[0:70])"'); then
  [ -n "$out" ] && echo "$out"
  emit "issues.priority_high=$(grep -oE '^#[0-9]+' <<<"$out" | tr -d '#' | paste -sd, -)"
else
  fail "issue list"
fi

echo "== main since the previous run"
if [ -z "$prev_sha" ]; then
  echo "first run: no previous snapshot"
elif [ "$prev_sha" = "$m" ]; then
  echo "no commits since ${m:0:7}"
elif git merge-base --is-ancestor "$prev_sha" "$m" 2>/dev/null; then
  n=$(git rev-list --count "$prev_sha..$m")
  echo "$n commits, ${prev_sha:0:7}..${m:0:7}:"
  git log --oneline "$prev_sha..$m" | head -"$cap"
  [ "$n" -le "$cap" ] || echo "... and $((n - cap)) more commits"
  files=$(git diff --name-only "$prev_sha" "$m")
  nf=$(grep -c . <<<"$files")
  echo "$nf files changed:"
  head -"$cap" <<<"$files"
  [ "$nf" -le "$cap" ] || echo "... and $((nf - cap)) more files"
else
  echo "REWRITTEN: the previous snapshot's commit ${prev_sha:0:7} is not an ancestor of main"
fi

echo "== deep audit"
if [ -r "$state/deep-run" ] && read -r depoch ddate dsha dtool < "$state/deep-run"; then
  dage=$(( (now - depoch) / 86400 ))
  echo "last: $dtool on $ddate at $dsha (${dage}d ago)"
  if [ "$dage" -gt "$deep_days" ]; then due=yes; else due=no; fi
else
  echo "last: none recorded"
  due=yes
fi
echo "due=$due (every $deep_days days)"

echo "== changed since the previous run"
if [ "$rc" -ne 0 ]; then
  echo "not compared and not saved: a section failed"
elif [ -z "$prev" ]; then
  echo "first run: baseline recorded"
else
  d=$(diff <(grep -v '^#' "$prev" | sort) <(grep -v '^#' "$new" | sort) | grep '^[<>]' | sed 's/^</was:/; s/^>/now:/')
  if [ -n "$d" ]; then echo "$d"; else echo "no change"; fi
fi
if [ "$rc" -eq 0 ]; then
  saved="$state/snapshot-$(date -u +%Y%m%dT%H%M%SZ)-${m:0:7}.txt"
  if cp "$new" "$saved"; then echo "saved: $saved"; else fail "snapshot save"; fi
fi
exit $rc
