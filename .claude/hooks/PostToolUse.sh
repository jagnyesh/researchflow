#!/usr/bin/env bash
# PostToolUse hook — runs after Edit/Write to give fast feedback on critical paths.
#
# Reads Claude Code's JSON tool-call payload from stdin. Side effects only — exit
# code is mostly informational. Slow operations are backgrounded so they never
# block Claude's next turn.

set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then exit 0; fi

input="$(cat)"
tool=$(echo "$input" | jq -r '.tool_name // empty')

case "$tool" in
  Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

path=$(echo "$input" | jq -r '.tool_input.file_path // empty')
[[ -z "$path" ]] && exit 0

# Repo root (assumes hook lives at $REPO/.claude/hooks/)
repo="$(cd "$(dirname "$0")/../.." && pwd)"
log="$repo/.claude/hooks/posttooluse.log"
mkdir -p "$(dirname "$log")"

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# 1. Auto-pytest on agent / SQL-on-FHIR edits
if [[ "$path" == *"/app/agents/"*.py ]] || [[ "$path" == *"/app/sql_on_fhir/"*.py ]]; then
  base=$(basename "$path" .py)
  test_file=""
  for candidate in \
    "$repo/tests/test_${base}.py" \
    "$repo/tests/integration/test_${base}.py" \
    "$repo/tests/workflows/test_${base}.py"; do
    [[ -f "$candidate" ]] && test_file="$candidate" && break
  done
  if [[ -n "$test_file" ]]; then
    nohup bash -c "
      cd '$repo' && \
      source .venv/bin/activate 2>/dev/null && \
      pytest '$test_file' -x --tb=line >> '$log' 2>&1
      echo \"[$(ts)] $test_file exit=\$?\" >> '$log'
    " >/dev/null 2>&1 &
    echo "[$(ts)] backgrounded: pytest $test_file (after $path)" >> "$log"
  fi
fi

# 2. Sync check on living-state docs
case "$(basename "$path")" in
  CLAUDE.md|CONTEXT.md|DECISIONS.md|BACKLOG.md|architecture.rules)
    echo "[$(ts)] STATE FILE CHANGED: $path — verify CONTEXT.md still matches git log -10" >&2
    ;;
esac

exit 0
