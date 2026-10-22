#!/usr/bin/env bash
# SessionStart hook — runs once per Claude Code session.
#
# Four checks (all warn-only, never block session start):
#   1. .env contains no sentinel placeholders (e.g. sk-ant-api03-...)
#   2. Redis is reachable (Sprint 6.1 audit pipeline depends on it)
#   3. Echo current sprint banner from CONTEXT.md
#   4. Lane check: red main, review debt, open PRs (DAILY_DEV_WORKFLOW §10)

set -uo pipefail

repo="$(cd "$(dirname "$0")/../.." && pwd)"
banner=()

# 1. .env sentinel scan
env_file="$repo/.env"
if [[ -f "$env_file" ]]; then
  # Catch sentinel placeholders (literal "sk-ant-api03-" with no real key suffix
  # = unreplaced template). Real keys are ~95+ chars; placeholders are short.
  if grep -qE '=(sk-ant-api03-|lsv2_pt_|your-api-key|YOUR_KEY|CHANGE_ME|REPLACE_ME)\.\.\.' "$env_file"; then
    banner+=("⚠️  .env contains a sentinel placeholder — fill in real values before running.")
  fi
  # Also flag suspiciously short ANTHROPIC_API_KEY values
  if grep -qE '^ANTHROPIC_API_KEY=.{0,30}$' "$env_file" 2>/dev/null && ! grep -qE '^ANTHROPIC_API_KEY=$' "$env_file"; then
    banner+=("⚠️  ANTHROPIC_API_KEY in .env looks too short to be a real key.")
  fi
else
  banner+=("ℹ️  No .env file at repo root (cp config/.env.example .env).")
fi

# 2. Redis reachability
if command -v redis-cli >/dev/null 2>&1; then
  if redis-cli -t 1 ping >/dev/null 2>&1; then
    : # silent on success
  else
    banner+=("⚠️  Redis unreachable — Sprint 6.1 audit drain + speed layer will fail. Start with: redis-server &")
  fi
else
  banner+=("ℹ️  redis-cli not installed (brew install redis).")
fi

# 3. Sprint banner from CONTEXT.md
ctx="$repo/CONTEXT.md"
if [[ -f "$ctx" ]]; then
  sprint_line=$(grep -m1 -E '^\*\*Sprint:\*\*' "$ctx" | sed 's/\*\*//g')
  phase_line=$(grep -m1 -E '^\*\*Phase:\*\*' "$ctx" | sed 's/\*\*//g')
  branch=$(cd "$repo" && git branch --show-current 2>/dev/null)
  banner+=("📋 ${sprint_line:-Sprint: ?} | ${phase_line:-Phase: ?} | branch: ${branch:-detached}")
fi

# 4. Lane check. Desktop-app and cloud sessions never run scripts/lane.sh, so
# this is the one place every session sees the §10 rules (#196). Any failure
# prints a skip line: silence has to mean "checked and clear", not "didn't run".
with_timeout() {
  if command -v timeout >/dev/null 2>&1; then timeout "$@"
  else perl -e 'alarm shift; exec @ARGV' "$@"; fi
}

lane_check() {
  command -v gh >/dev/null 2>&1 || { echo "ℹ️  lane check skipped: gh not installed"; return; }
  command -v jq >/dev/null 2>&1 || { echo "ℹ️  lane check skipped: jq not installed"; return; }
  local tmp pr_pid run_pid pr_rc run_rc
  tmp=$(mktemp -d) || { echo "ℹ️  lane check skipped: mktemp failed"; return; }
  (cd "$repo" && with_timeout 8 gh pr list --state open --limit 30 \
     --json number,title,headRefName,isDraft,statusCheckRollup) >"$tmp/prs" 2>/dev/null &
  pr_pid=$!
  (cd "$repo" && with_timeout 8 gh run list --branch main --limit 20 \
     --json workflowName,conclusion,status,createdAt,headSha) >"$tmp/runs" 2>/dev/null &
  run_pid=$!
  wait "$pr_pid"; pr_rc=$?
  wait "$run_pid"; run_rc=$?
  if [[ $pr_rc -ne 0 || $run_rc -ne 0 ]]; then
    echo "ℹ️  lane check skipped: gh failed (offline, unauthenticated, or timed out)"
  elif ! jq -nr --slurpfile prs "$tmp/prs" --slurpfile runs "$tmp/runs" '
      # Latest completed run per workflow; a cancelled run is not a red pipeline.
      ($runs[0] | map(select(.status == "completed")) | group_by(.workflowName)
        | map(max_by(.createdAt))
        | map(select(.conclusion | IN("failure", "timed_out", "startup_failure")))
        | if length > 0 then
            "🚦 main CI red: \(map("\(.workflowName) @ \(.headSha[0:7])") | join(", ")) — §10: one lane until green"
          else empty end),
      # Awaiting a decision = open, not draft, every check finished and passing.
      ($prs[0] | map(select((.isDraft | not) and (.statusCheckRollup | length) > 0
          and all(.statusCheckRollup[]; ((.conclusion // "") + (.state // ""))
                                        | IN("SUCCESS", "SKIPPED", "NEUTRAL"))))
        | if length >= 2 then
            "🚦 \(length) PRs await your decision (\(map("#\(.number)") | join(", "))) — §10: no new lane at ≥2"
          else empty end),
      ($prs[0][] | "🚦 In flight: #\(.number) [\(.headRefName)] \(.title[0:60])")
    ' 2>/dev/null; then
    echo "ℹ️  lane check skipped: unexpected gh output"
  fi
  rm -rf "$tmp"
}

while IFS= read -r line; do banner+=("$line"); done < <(lane_check)

# Output banner — Claude sees this at session start
if [[ ${#banner[@]} -gt 0 ]]; then
  printf '%s\n' "${banner[@]}"
fi

exit 0
