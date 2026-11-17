#!/usr/bin/env bash
# red_first.sh — prove a new or changed test fails on the base before the change.
#
# usage: scripts/red_first.sh [--base <ref>] <test file or file::node id>...
#
# Builds a temporary worktree at the base (default: merge-base of HEAD and origin/main),
# copies in only the named test files from the lane's working tree, and runs each one,
# one pytest process per file, there and then here. Exit codes:
#   0  red on the base (pytest exit 1 or 2) and green here: the test can fail
#   1  not red-first: it passes on the base, collects nothing there, or fails here
#   2  usage error, or a path on .claude/lane-never-run.txt (nothing ran)
#   3  the code under test would be imported from the lane's checkout, not the base tree
#   4  a run timed out or pytest itself broke (exit 3, 4 or 6)
# Env: RED_FIRST_PYTHON (default <repo>/.venv/bin/python, else python3), RED_FIRST_PACKAGE
# (the top-level package the import-path check probes; default app),
# RED_FIRST_TIMEOUT (seconds per run; default 600).
set -uo pipefail
exec python3 -I - "$@" <<'PY'
import os, re, shutil, signal, subprocess, sys, tempfile

args = sys.argv[1:]
base_ref = None
targets = []
while args:
    a = args.pop(0)
    if a == "--base":
        if not args:
            sys.exit("usage: red_first.sh [--base <ref>] <test file or file::node id>...")
        base_ref = args.pop(0)
    else:
        targets.append(a)
if not targets:
    sys.stderr.write("usage: red_first.sh [--base <ref>] <test file or file::node id>...\n")
    sys.exit(2)

def run(*cmd, cwd, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)

top = run("git", "rev-parse", "--show-toplevel", cwd=os.getcwd())
if top.returncode != 0:
    sys.stderr.write("red_first: not inside a git repository\n")
    sys.exit(2)
repo = os.path.realpath(top.stdout.strip())

# The never-run list is read the way .claude/hooks/Stop.sh reads it (same comment
# stripping, same three entry kinds, same fail-closed rule).
def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""

deny_files, deny_markers, deny_patterns = set(), [], []
for line in read(os.path.join(repo, ".claude/lane-never-run.txt")).splitlines():
    line = re.split(r"(?:^|\s)#", line, maxsplit=1)[0].strip()
    if line.startswith("pattern:"):
        deny_patterns.append(re.compile(line[8:].strip()))
    elif line.startswith("file:"):
        deny_files.add(line[5:].strip())
    elif line.startswith("marker:"):
        deny_markers.append(line[7:].strip())
if not (deny_files or deny_markers or deny_patterns):
    sys.stderr.write("red_first: .claude/lane-never-run.txt is missing or empty; ran nothing\n")
    sys.exit(2)

def refusal(rel):
    if rel in deny_files:
        return "on .claude/lane-never-run.txt"
    text = read(os.path.join(repo, rel))
    for m in deny_markers:
        if re.search(r"\b%s\b" % re.escape(m), text):
            return "marked " + m
    for p in deny_patterns:
        if p.search(text):
            return "matches never-run pattern " + p.pattern
    return None

files = []  # (relative file, original target)
for t in targets:
    rel = os.path.normpath(t.split("::", 1)[0])
    if os.path.isabs(rel) or rel.startswith(".."):
        sys.stderr.write("red_first: %s is outside the repo\n" % t)
        sys.exit(2)
    if not os.path.isfile(os.path.join(repo, rel)):
        sys.stderr.write("red_first: %s does not exist in the working tree\n" % rel)
        sys.exit(2)
    why = refusal(rel)
    if why:
        sys.stderr.write("red_first: refusing %s (%s); ran nothing\n" % (rel, why))
        sys.exit(2)
    files.append((rel, t))

if base_ref is None:
    mb = run("git", "merge-base", "HEAD", "origin/main", cwd=repo)
    if mb.returncode != 0:
        sys.stderr.write("red_first: no merge-base with origin/main; pass --base\n")
        sys.exit(2)
    base_ref = mb.stdout.strip()
base = run("git", "rev-parse", "--verify", base_ref + "^{commit}", cwd=repo)
if base.returncode != 0:
    sys.stderr.write("red_first: unknown base %s\n" % base_ref)
    sys.exit(2)
base_sha = base.stdout.strip()

venv_py = os.path.join(repo, ".venv", "bin", "python")
py = os.environ.get("RED_FIRST_PYTHON") or (venv_py if os.path.exists(venv_py) else "python3")
package = os.environ.get("RED_FIRST_PACKAGE", "app")
timeout = int(os.environ.get("RED_FIRST_TIMEOUT", "600"))
env = dict(os.environ, ANTHROPIC_API_KEY="", LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false")

scratch = tempfile.mkdtemp(prefix="red_first_")
wt = os.path.realpath(os.path.join(scratch, "base"))

def cleanup():
    subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo, capture_output=True)
    shutil.rmtree(scratch, ignore_errors=True)
    subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)

def on_term(signum, frame):
    sys.exit(128 + signum)
signal.signal(signal.SIGTERM, on_term)
signal.signal(signal.SIGHUP, on_term)

PROBE = (
    "import importlib.util, os, sys\n"
    "try:\n"
    "    s = importlib.util.find_spec(sys.argv[1])\n"
    "except ImportError:\n"
    "    s = None\n"
    "if s is not None:\n"
    "    locs = list(s.submodule_search_locations or [])\n"
    "    if s.origin and s.origin != 'namespace': locs.append(s.origin)\n"
    "    for l in locs: print(os.path.realpath(l))\n"
)

def pytest(cwd, target):
    try:
        return subprocess.run(
            [py, "-m", "pytest", target, "-q", "-p", "no:cacheprovider", "--tb=short"],
            cwd=cwd, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None

try:
    add = run("git", "worktree", "add", "--detach", wt, base_sha, cwd=repo)
    if add.returncode != 0:
        sys.stderr.write("red_first: could not create the base worktree: %s\n" % add.stderr.strip())
        sys.exit(2)

    # The package must resolve to the base tree. An editable install or a stray
    # PYTHONPATH that points at this checkout would run the change's code in both runs.
    probe = subprocess.run([py, "-c", PROBE, package], cwd=wt, env=env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
    if probe.returncode != 0:
        sys.stderr.write("red_first: import-path probe failed: %s\n" % probe.stderr.strip())
        sys.exit(4)
    stray = [p for p in probe.stdout.splitlines() if p != wt and not p.startswith(wt + os.sep)]
    if stray:
        sys.stderr.write(
            "red_first: import-path check failed: package %r resolves to %s, outside the base tree %s.\n"
            "The base run would execute this checkout's code. Fix the editable install, .pth file or "
            "PYTHONPATH.\n" % (package, stray[0], wt))
        sys.exit(3)

    for rel, _ in files:
        dest = os.path.join(wt, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(os.path.join(repo, rel), dest)

    for rel, target in files:
        b = pytest(wt, target)
        if b is None:
            sys.stderr.write("red_first: base run of %s timed out after %ds\n" % (target, timeout))
            sys.exit(4)
        out = (b.stdout + b.stderr).rstrip()
        if b.returncode in (3, 4, 6):
            sys.stderr.write("red_first: pytest broke on the base run of %s (exit %d):\n%s\n" % (target, b.returncode, out))
            sys.exit(4)
        if b.returncode == 5:
            sys.stderr.write("red_first: %s collected no tests on the base; nothing proves it can fail.\n%s\n" % (target, out))
            sys.exit(1)
        if b.returncode == 0:
            sys.stderr.write(
                "red_first: %s PASSES on the base %s; it does not test the change.\n%s\n" % (target, base_sha[:12], out))
            sys.exit(1)

        h = pytest(repo, target)
        if h is None:
            sys.stderr.write("red_first: run of %s here timed out after %ds\n" % (target, timeout))
            sys.exit(4)
        if h.returncode != 0:
            sys.stderr.write("red_first: %s fails here too (pytest exit %d):\n%s\n" % (target, h.returncode, (h.stdout + h.stderr).rstrip()))
            sys.exit(1)

        print("Red-first: %s: base %s pytest exit %d (red); here pytest exit 0 (green)" % (target, base_sha[:12], b.returncode))
        print("--- base run output ---")
        print(out)
        print("--- end base run output ---")
finally:
    cleanup()
PY
