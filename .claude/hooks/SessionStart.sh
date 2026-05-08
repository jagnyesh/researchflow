#!/usr/bin/env bash
# SessionStart hook — runs once per Claude Code session.
#
# Three checks (all warn-only, never block session start):
#   1. .env contains no sentinel placeholders (e.g. sk-ant-api03-...)
#   2. Redis is reachable (Sprint 6.1 audit pipeline depends on it)
#   3. Echo current sprint banner from CONTEXT.md

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

# Output banner — Claude sees this at session start
if [[ ${#banner[@]} -gt 0 ]]; then
  printf '%s\n' "${banner[@]}"
fi

exit 0
