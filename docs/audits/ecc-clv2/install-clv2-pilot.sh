#!/usr/bin/env bash
# Install the gap 3 learning-loop pilot into ONE sandbox repo.
#
# What it does, and nothing else:
#   1. Fetches ECC at the vetted commit d2ef268 (full SHA checked) into a temp dir.
#   2. Copies skills/continuous-learning-v2 (minus SKILL.md, so it is not a skill
#      the model can invoke) to <repo>/.claude/clv2 and applies clv2-local.patch.
#   3. Writes <repo>/.claude/clv2/observe-sandbox.sh, which pins the env and runs
#      the hook, and <repo>/.homunculus/config.json (observer enabled).
#   4. Adds PreToolUse/PostToolUse hooks to <repo>/.claude/settings.local.json
#      (uncommitted, per-machine) and .homunculus/ to .git/info/exclude.
# It never touches ~/.claude, shell rc files, or any other repo.
#
# Usage: install-clv2-pilot.sh <sandbox-repo>      (uninstall: --uninstall <repo>)
set -euo pipefail

ECC_URL=https://github.com/affaan-m/ECC.git
ECC_SHA=d2ef2680594f9a17526a6e1a2e18b3d242c5d17b
HERE="$(cd "$(dirname "$0")" && pwd)"
PATCH="$HERE/clv2-local.patch"

if [ "${1:-}" = "--uninstall" ]; then
  REPO="$(cd "$2" && pwd)"
  [ -f "$REPO/.homunculus/.observer.pid" ] && kill "$(cat "$REPO/.homunculus/.observer.pid")" 2>/dev/null || true
  find "$REPO/.homunculus" -name .observer.pid -exec sh -c 'kill "$(cat "$1")" 2>/dev/null || true' _ {} \; 2>/dev/null || true
  rm -rf "$REPO/.claude/clv2"
  python3 -I - "$REPO/.claude/settings.local.json" <<'PY'
import json, sys, os
p = sys.argv[1]
if os.path.exists(p):
    s = json.load(open(p))
    for ev in ("PreToolUse", "PostToolUse"):
        groups = s.get("hooks", {}).get(ev, [])
        groups[:] = [g for g in groups if "clv2/observe-sandbox.sh" not in json.dumps(g)]
        if not groups: s.get("hooks", {}).pop(ev, None)
    if not s.get("hooks"): s.pop("hooks", None)
    json.dump(s, open(p, "w"), indent=2); open(p, "a").write("\n")
PY
  echo "Removed hooks and .claude/clv2. Instincts and logs kept in $REPO/.homunculus (delete by hand)."
  exit 0
fi

REPO="$(cd "${1:?usage: $0 <sandbox-repo>}" && pwd)"
git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null
[ -f "$PATCH" ] || { echo "missing $PATCH" >&2; exit 1; }
[ -e "$REPO/.claude/clv2" ] && { echo "$REPO/.claude/clv2 exists; run --uninstall first" >&2; exit 1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git -C "$TMP" init -q
git -C "$TMP" fetch -q --depth 1 "$ECC_URL" "$ECC_SHA"
[ "$(git -C "$TMP" rev-parse FETCH_HEAD)" = "$ECC_SHA" ] || { echo "SHA mismatch" >&2; exit 1; }
git -C "$TMP" -c advice.detachedHead=false checkout -q FETCH_HEAD -- skills/continuous-learning-v2

mkdir -p "$REPO/.claude"
cp -R "$TMP/skills/continuous-learning-v2" "$REPO/.claude/clv2"
rm -f "$REPO/.claude/clv2/SKILL.md"
(cd "$REPO/.claude/clv2" && patch -p1 --forward --quiet < "$PATCH")
grep -q 'LOCAL PATCH (researchflow vet' "$REPO/.claude/clv2/agents/observer-loop.sh"

cat > "$REPO/.claude/clv2/observe-sandbox.sh" <<'SH'
#!/usr/bin/env bash
# Pilot wrapper: pins every path the hook and the analyzer use to <repo>/.homunculus.
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
export CLV2_HOMUNCULUS_DIR="$REPO/.homunculus"
export CLV2_CONFIG="$CLV2_HOMUNCULUS_DIR/config.json"
export CLV2_PYTHON_CMD=python3
export OBSERVER_LAST_RUN_LOG="$CLV2_HOMUNCULUS_DIR/observer-last-run.log"
exec bash "$REPO/.claude/clv2/hooks/observe.sh" "$@"
SH
chmod +x "$REPO/.claude/clv2/observe-sandbox.sh" "$REPO/.claude/clv2/hooks/observe.sh" "$REPO/.claude/clv2/agents/"*.sh

mkdir -p "$REPO/.homunculus"; chmod 700 "$REPO/.homunculus"
[ -f "$REPO/.homunculus/config.json" ] || cat > "$REPO/.homunculus/config.json" <<'JSON'
{
  "version": "2.1",
  "observer": { "enabled": true, "run_interval_minutes": 5, "min_observations_to_analyze": 20 }
}
JSON

EXCL="$(git -C "$REPO" rev-parse --git-path info/exclude)"
case "$EXCL" in /*) ;; *) EXCL="$REPO/$EXCL" ;; esac
mkdir -p "$(dirname "$EXCL")"; touch "$EXCL"
for pat in /.homunculus/ /.claude/clv2/ /.claude/settings.local.json; do
  grep -qxF "$pat" "$EXCL" || echo "$pat" >> "$EXCL"
done

python3 -I - "$REPO/.claude/settings.local.json" <<'PY'
import json, sys, os
p = sys.argv[1]
s = json.load(open(p)) if os.path.exists(p) else {}
for ev, phase in (("PreToolUse", "pre"), ("PostToolUse", "post")):
    groups = s.setdefault("hooks", {}).setdefault(ev, [])
    if any("clv2/observe-sandbox.sh" in json.dumps(g) for g in groups):
        continue
    groups.append({"matcher": "*", "hooks": [{"type": "command",
        "command": f'bash "$CLAUDE_PROJECT_DIR/.claude/clv2/observe-sandbox.sh" {phase}',
        "timeout": 10}]})
json.dump(s, open(p, "w"), indent=2); open(p, "a").write("\n")
PY

echo "Installed pilot in $REPO"
echo "  hooks:     .claude/settings.local.json (PreToolUse + PostToolUse)"
echo "  code:      .claude/clv2 (ECC $ECC_SHA + clv2-local.patch)"
echo "  data:      .homunculus/ (observations, instincts, logs)"
echo "  instincts: .homunculus/projects/*/instincts/personal/"
