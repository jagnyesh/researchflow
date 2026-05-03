#!/usr/bin/env bash
# PreToolUse hook — Sprint 6.1 security guardrail.
#
# Reads Claude Code's JSON tool-call payload from stdin and either:
#   - exits 0 to allow the call,
#   - exits 2 (with stderr message) to block it.
#
# Fail-open: if jq is missing or input parse fails, allow and warn.

set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "PreToolUse: jq missing, allowing all tool calls (install: brew install jq)" >&2
  exit 0
fi

input="$(cat)"
tool=$(echo "$input" | jq -r '.tool_name // empty')

case "$tool" in
  Edit|Write|MultiEdit|NotebookEdit)
    path=$(echo "$input" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
    [[ -z "$path" ]] && exit 0

    # Block PHI test fixtures
    if [[ "$path" == *"/phi_test_data/"* ]] || [[ "$path" == *"/synthetic_phi/"* ]]; then
      echo "BLOCKED: $path is in a PHI fixture path. Sprint 6.1 disallows direct edits — generate via fixture builder instead." >&2
      exit 2
    fi

    # Block writes to legacy archive (post-LangGraph-rollout zone)
    if [[ "$path" == *"/app/legacy/"* ]]; then
      echo "BLOCKED: $path is under app/legacy/. Reserved for post-LangGraph archive — don't write here yet." >&2
      exit 2
    fi
    ;;

  Bash)
    cmd=$(echo "$input" | jq -r '.tool_input.command // empty')
    [[ -z "$cmd" ]] && exit 0

    # Warn on string-interpolated SQL via psql/sqlite3 — likely SQL injection vector
    if echo "$cmd" | grep -qE '(psql|sqlite3)\b' && echo "$cmd" | grep -qE '\$\{[^}]+\}|f"[^"]*\{|\.format\('; then
      echo "WARN: psql/sqlite3 invocation appears to use string interpolation. Sprint 6 hard rule: parameterized queries only. Use SQLAlchemy text() with bound params." >&2
      # Warn-only for now (exit 0); flip to exit 2 once team is comfortable
      exit 0
    fi

    # Block destructive commands without explicit safeguard
    if echo "$cmd" | grep -qE 'rm -rf? /( |$|\*)|DROP DATABASE|DROP TABLE|TRUNCATE TABLE'; then
      echo "BLOCKED: command looks destructive (rm -rf /, DROP DATABASE, etc.). Re-issue with explicit scope or in a wrapped script if intentional." >&2
      exit 2
    fi
    ;;
esac

exit 0
