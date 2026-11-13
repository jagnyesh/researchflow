#!/usr/bin/env bash
# Stop hook — before a lane session ends its turn, run the tests its change can break.
#
# Exit 2 (stderr goes back to Claude) when a test file fails, so the session fixes it
# instead of reporting done and finding out in CI. Exit 0 in every other case.
#
# Never-run list: .claude/lane-never-run.txt (shared with the plan-lanes brief).
# Each file runs in its own pytest process: a multi-file run here has hung for hours.

set -uo pipefail

input="$(cat)"

# A fix the session can't make would otherwise trap it in a loop: the second Stop is
# the re-entry after we already sent it back once.
if command -v jq >/dev/null 2>&1; then
  [[ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false')" == "true" ]] && exit 0
else
  printf '%s' "$input" | grep -Eq '"stop_hook_active"[[:space:]]*:[[:space:]]*true' && exit 0
fi

command -v python3 >/dev/null 2>&1 || exit 0

repo="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo" || exit 0

# The coordinating session lives in the main checkout; lanes live in worktrees.
[[ "$(git rev-parse --git-dir 2>/dev/null)" == "$(git rev-parse --git-common-dir 2>/dev/null)" ]] && exit 0

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
case "$branch" in
  feat/*|fix/*|chore/*|ci/*|docs/*|claude/*) ;;
  *) exit 0 ;;
esac

git rev-parse --verify -q origin/main >/dev/null || exit 0

exec python3 -I - "$repo" <<'PY'
import ast, json, os, re, subprocess, sys, time

repo = sys.argv[1]
TOTAL_BUDGET = 480   # seconds across all files; settings.json's timeout must exceed this
PER_FILE = 150       # seconds for one file

def git(*args):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []

base = (git("merge-base", "HEAD", "origin/main") or [""])[0]
if not base:
    sys.exit(0)
changed = set(git("diff", "--no-renames", "--name-only", base)) | set(git("ls-files", "-o", "--exclude-standard"))
# A deleted or renamed app module still breaks its importers, so only tests need to exist.
app_changed = sorted(c for c in changed if c.startswith("app/") and c.endswith(".py"))
tests_changed = sorted(
    c for c in changed
    if c.startswith("tests/") and c.endswith(".py") and os.path.exists(os.path.join(repo, c))
)
if not app_changed and not tests_changed:
    sys.exit(0)

def read(rel):
    try:
        with open(os.path.join(repo, rel), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""

# Never-run list.
deny_files, deny_markers, deny_patterns = set(), [], []
for line in read(".claude/lane-never-run.txt").splitlines():
    line = re.split(r"(?:^|\s)#", line, maxsplit=1)[0].strip()
    if line.startswith("pattern:"):
        deny_patterns.append(re.compile(line[8:].strip()))
    elif line.startswith("file:"):
        deny_files.add(line[5:].strip())
    elif line.startswith("marker:"):
        deny_markers.append(line[7:].strip())

if not (deny_files or deny_markers or deny_patterns):
    # Fail closed: without the list the hook can't tell which files are unsafe to run.
    sys.stderr.write("Stop hook: .claude/lane-never-run.txt is missing or empty; ran no tests.\n")
    sys.exit(0)

def skip_reason(rel):
    if rel in deny_files:
        return "on .claude/lane-never-run.txt"
    text = read(rel)
    for m in deny_markers:
        if re.search(r"\b%s\b" % re.escape(m), text):
            return "marked " + m
    for p in deny_patterns:
        if p.search(text):
            return "matches never-run pattern " + p.pattern
    return None

# Test files that import (or patch) a changed app module.
all_tests = []
for root, dirs, files in os.walk(os.path.join(repo, "tests")):
    dirs[:] = [d for d in dirs if d not in ("__pycache__", "fixtures")]
    for fn in files:
        if fn.endswith(".py") and (fn.startswith("test_") or fn.endswith("_test.py")):
            all_tests.append(os.path.relpath(os.path.join(root, fn), repo))

matchers = []
for f in app_changed:
    mod = f[:-3].replace("/", ".")
    if mod.endswith(".__init__"):
        mod = mod[: -len(".__init__")]
    pkg, _, leaf = mod.rpartition(".")
    pats = [r"\b%s\b" % re.escape(mod)]
    if pkg:
        pats.append(r"from\s+%s\s+import\s+[^\n]*\b%s\b" % (re.escape(pkg), re.escape(leaf)))
    matchers.append(re.compile("|".join(pats)))

def imported_modules(text):
    """Dotted names a test imports, from the AST so multi-line and continued imports count."""
    names = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(node.module + "." + a.name for a in node.names)
    return names

changed_mods = set()
for f in app_changed:
    mod = f[:-3].replace("/", ".")
    changed_mods.add(mod[: -len(".__init__")] if mod.endswith(".__init__") else mod)

def covers(text):
    if any(m.search(text) for m in matchers):  # also catches mock.patch("app.x.y.fn") strings
        return True
    return any(i == c or i.startswith(c + ".") for i in imported_modules(text) for c in changed_mods)

targets = set(tests_changed)
if matchers:
    for t in all_tests:
        if covers(read(t)):
            targets.add(t)

env = dict(os.environ, ANTHROPIC_API_KEY="", LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false")
venv_py = os.path.join(repo, ".venv", "bin", "python")
py = venv_py if os.path.exists(venv_py) else "python3"

not_run, failures, ran = [], [], 0
start = time.time()
for t in sorted(targets):
    why = skip_reason(t)
    if why:
        not_run.append("%s (%s)" % (t, why))
        continue
    left = TOTAL_BUDGET - (time.time() - start)
    if left <= 5:
        not_run.append("%s (total time limit)" % t)
        continue
    try:
        r = subprocess.run(
            [py, "-m", "pytest", t, "-q", "-x", "--tb=short", "-rfE", "-p", "no:cacheprovider"],
            cwd=repo, env=env, capture_output=True, text=True, timeout=min(PER_FILE, left),
        )
    except subprocess.TimeoutExpired:
        not_run.append("%s (timed out after %ds)" % (t, min(PER_FILE, left)))
        continue
    except OSError as e:
        not_run.append("%s (could not start pytest: %s)" % (t, e))
        continue
    ran += 1
    if r.returncode not in (0, 5):
        names = [l for l in r.stdout.splitlines() if l.startswith(("FAILED ", "ERROR "))]
        tail = (r.stdout + r.stderr).strip().splitlines()[-8:]
        failures.append((t, names or ["(pytest exit %d, no FAILED line; last output:)" % r.returncode] + tail))

if not_run:
    msg = "Stop hook: not run (%d): %s" % (len(not_run), "; ".join(not_run))
    sys.stderr.write(msg + "\n")
    if not failures:
        # exit-0 stderr is only visible in verbose mode; systemMessage reaches the user.
        print(json.dumps({"systemMessage": msg}))
if not failures:
    sys.exit(0)

out = ["Stop hook: %d of %d affected test file(s) fail. Fix them before ending the turn:" % (len(failures), ran)]
for t, names in failures:
    out.append("  %s" % t)
    out.extend("    " + n for n in names)
    out.append("    rerun: ANTHROPIC_API_KEY= LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false .venv/bin/python -m pytest -xvs %s" % t)
out.append("If a failure can't be fixed in this session, say so in your report; the hook won't block a second stop.")
sys.stderr.write("\n".join(out) + "\n")
sys.exit(2)
PY
