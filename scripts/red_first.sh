#!/usr/bin/env bash
# red_first.sh — prove a new or changed test fails on the base before the change.
#
# usage: scripts/red_first.sh [--base <ref>] <test file or file::node id>...
#
# Builds a temporary worktree at the base (default: merge-base of HEAD and origin/main),
# copies in the named test files and every test-support file the change touches (anything
# under tests/, any conftest.py, and the root pytest.ini, pyproject.toml, setup.cfg and
# tox.ini) from the lane's working tree, and runs each target, one pytest process per
# target, there and then here. "Here" is the working tree, committed or not, so the
# Red-first line carries the HEAD SHA and "+uncommitted" when the tree was dirty. Exit codes:
#   0  red on the base (pytest exit 1 or 2) and green here (at least one test passed)
#   1  not red-first: it passes on the base, collects nothing there, or here it fails or
#      passes no test (an all-skipped run is not green)
#   2  usage error (including a bad RED_FIRST_TIMEOUT), or a path on
#      .claude/lane-never-run.txt, matched by the file it names (nothing ran)
#   3  the code under test would be imported from the lane's checkout, not the base tree
#   4  a run timed out, pytest itself broke (exit 3, 4 or 6), or RED_FIRST_PYTHON can't run
#      pytest
# A base red that is only a collection error (pytest exit 2) is accepted and flagged: it
# proves the test needs the change in order to import, not that an assertion can fail.
# Env: RED_FIRST_PYTHON (default <repo>/.venv/bin/python, else python3), RED_FIRST_PACKAGE
# (the top-level packages the import-path check probes, comma-separated; default app),
# RED_FIRST_TIMEOUT (seconds per run; default 600).
set -uo pipefail
exec python3 -I - "$@" <<'PY'
import os, re, shutil, signal, subprocess, sys, tempfile

USAGE = "usage: red_first.sh [--base <ref>] <test file or file::node id>...\n"
args = sys.argv[1:]
base_ref = None
targets = []
while args:
    a = args.pop(0)
    if a == "--base":
        if not args:
            sys.stderr.write(USAGE)
            sys.exit(2)
        base_ref = args.pop(0)
    else:
        targets.append(a)
if not targets:
    sys.stderr.write(USAGE)
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
    # By file, not by spelling: a symlink, a hard link or (on a case-insensitive
    # filesystem) a case variant of a listed path is the same file.
    here = os.path.join(repo, rel)
    for d in deny_files:
        listed = os.path.join(repo, os.path.normpath(d))
        if rel == os.path.normpath(d) or (os.path.exists(listed) and os.path.samefile(here, listed)):
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

head = run("git", "rev-parse", "HEAD", cwd=repo)
if head.returncode != 0:
    sys.stderr.write("red_first: no HEAD commit\n")
    sys.exit(2)
# Read before any pytest run, which can leave untracked files of its own.
here_sha = head.stdout.strip()[:12]
if run("git", "status", "--porcelain", cwd=repo).stdout.strip():
    here_sha += "+uncommitted"

venv_py = os.path.join(repo, ".venv", "bin", "python")
py = os.environ.get("RED_FIRST_PYTHON") or (venv_py if os.path.exists(venv_py) else "python3")
packages = [p.strip() for p in os.environ.get("RED_FIRST_PACKAGE", "app").split(",") if p.strip()]
try:
    timeout = int(os.environ.get("RED_FIRST_TIMEOUT", "600"))
    if timeout <= 0:
        raise ValueError
except ValueError:
    sys.stderr.write("red_first: RED_FIRST_TIMEOUT must be a whole number of seconds, got %r\n"
                     % os.environ.get("RED_FIRST_TIMEOUT"))
    sys.exit(2)
env = dict(os.environ, ANTHROPIC_API_KEY="", LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false")

try:
    have_pytest = subprocess.run([py, "-m", "pytest", "--version"], cwd=repo, env=env, capture_output=True,
                                 text=True, stdin=subprocess.DEVNULL, timeout=timeout)
except (OSError, subprocess.TimeoutExpired) as e:
    sys.stderr.write("red_first: cannot run %s -m pytest: %s\n" % (py, e))
    sys.exit(4)
if have_pytest.returncode != 0:
    sys.stderr.write("red_first: %s -m pytest --version failed; set RED_FIRST_PYTHON to a python with pytest:\n%s\n"
                     % (py, (have_pytest.stdout + have_pytest.stderr).strip()))
    sys.exit(4)

scratch = tempfile.mkdtemp(prefix="red_first_")
wt = os.path.realpath(os.path.join(scratch, "base"))

children = []

def kill_group(p):
    # pytest runs in its own session, so this reaches the processes a test started too.
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

def cleanup():
    for p in children:
        kill_group(p)
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
    # No -q of our own: a project's addopts may already carry one, and -qq drops the totals
    # line. --no-header keeps the platform and rootdir lines (a local path) out of the output.
    p = subprocess.Popen(
        [py, "-m", "pytest", target, "--no-header", "-p", "no:cacheprovider", "--tb=short"],
        cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )
    children.append(p)  # stays listed until pytest returns, so a signal's cleanup() still kills it
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(p)
        try:
            p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass  # a descendant that left the group still holds the pipes
        children.remove(p)
        return None
    children.remove(p)
    return subprocess.CompletedProcess(p.args, p.returncode, out, err)

# pytest's own totals line: "== 1 passed, 1 skipped in 0.02s ==", or the same without the "="
# decoration under a project -q. Other text (a skip reason, a print at exit) can say "N passed"
# too, so a line counts only when it has this shape, and the decorated form wins.
DECORATED = re.compile(r"^=+ (.+) in [\d.]+s(?: \([\d:]+\))? =+$")
PLAIN = re.compile(r"^((?:\d+ \w[\w ]*?)(?:, \d+ \w[\w ]*?)*) in [\d.]+s(?: \([\d:]+\))?$")

def totals(r):
    lines = [l.rstrip() for l in r.stdout.splitlines() if l.strip()]
    for rx in (DECORATED, PLAIN):
        for l in reversed(lines):
            m = rx.match(l)
            if m:
                return l.strip("= "), m.group(1)
    return None, ""

def summary(r):
    line, _ = totals(r)
    return line or "no totals line"

def passed(r):
    m = re.search(r"(\d+) passed", totals(r)[1])
    return int(m.group(1)) if m else 0

def scrub(text):
    # The output goes into a PR: keep the scratch worktree, this checkout and the home
    # directory out of it.
    for path, label in ((wt, "<base>"), (scratch, "<scratch>"), (os.path.realpath(scratch), "<scratch>"),
                        (repo, "<repo>"), (os.path.expanduser("~"), "~")):
        if path and path != "/":
            text = text.replace(path, label)
    return text

SUPPORT_CONFIG = {"pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"}

def support_files():
    # Everything the change touches that a test run reads besides the test itself: without
    # these the base run goes red because a fixture, helper or marker is missing, not
    # because the code under test is.
    changed = set(run("git", "diff", "--name-only", "-z", "--no-renames", base_sha, cwd=repo).stdout.split("\0"))
    changed |= set(run("git", "ls-files", "--others", "--exclude-standard", "-z", cwd=repo).stdout.split("\0"))
    keep = []
    for rel in sorted(c for c in changed if c):
        parts = rel.split("/")
        if (parts[0] == "tests" and len(parts) > 1) or parts[-1] == "conftest.py" or rel in SUPPORT_CONFIG:
            if os.path.isfile(os.path.join(repo, rel)):
                keep.append(rel)
    return keep

try:
    add = run("git", "worktree", "add", "--detach", wt, base_sha, cwd=repo)
    if add.returncode != 0:
        sys.stderr.write("red_first: could not create the base worktree: %s\n" % add.stderr.strip())
        sys.exit(2)

    # The package must resolve to the base tree. An editable install or a stray
    # PYTHONPATH that points at this checkout would run the change's code in both runs.
    for package in packages:
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

    for rel in sorted({rel for rel, _ in files} | set(support_files())):
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
            sys.stderr.write("red_first: pytest broke on the base run of %s (exit %d). A conftest.py that "
                             "imports code the change adds can't load on the base:\n%s\n" % (target, b.returncode, out))
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
        here_out = (h.stdout + h.stderr).rstrip()
        if h.returncode in (3, 4, 6):
            sys.stderr.write("red_first: pytest broke on the run of %s here (exit %d):\n%s\n" % (target, h.returncode, here_out))
            sys.exit(4)
        if h.returncode != 0:
            sys.stderr.write("red_first: %s fails here too (pytest exit %d):\n%s\n" % (target, h.returncode, here_out))
            sys.exit(1)
        if passed(h) == 0:
            sys.stderr.write(
                "red_first: no test passed here for %s (%s); an all-skipped run proves nothing.\n%s\n"
                % (target, summary(h), here_out))
            sys.exit(1)

        print("Red-first: %s: base %s pytest exit %d (red); here %s pytest exit 0 (green: %s)"
              % (target, base_sha[:12], b.returncode, here_sha, summary(h)))
        if b.returncode == 2:
            print("Red-first note: %s: the base red is a collection error (pytest exit 2). It proves only that "
                  "the test needs the change in order to import; it does not show that an assertion can fail." % target)
        n_base = passed(b)
        if n_base:
            print("Red-first note: %s: %d test(s) pass on the base, so only the failing ones prove the change. "
                  "Pass file::node ids for the tests you added or changed." % (target, n_base))
        print("--- base run output ---")
        print(scrub(out))
        print("--- end base run output ---")
finally:
    cleanup()
PY
