"""#493: check.sh reports GitHub-side security state and what changed since the last run.

Runs the script against a throwaway git repo and a fake `gh` that trims its JSON to the
requested --json fields and applies -q with jq, as the real one does. Every value here is
made up; none describes the real repo.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

CHECK = Path(
    os.environ.get(
        "SECURITY_CHECK_SH",
        Path(__file__).resolve().parent.parent / ".claude/skills/security-check/check.sh",
    )
)

FAKE_GH = r"""#!__PYTHON__
import json, os, subprocess, sys
from pathlib import Path

args = sys.argv[1:]
data = json.loads(Path(os.environ["FAKE_GH_DATA"]).read_text())

def opt(name):
    return args[args.index(name) + 1] if name in args else None

def emit(obj):
    if isinstance(obj, dict) and "error" in obj:
        sys.exit(obj["error"])
    q = opt("-q")
    text = json.dumps(obj)
    if q is None:
        print(text)
    else:
        print(subprocess.run(["jq", "-r", q], input=text, capture_output=True, text=True, check=True).stdout, end="")

def trim(rows):
    fields = opt("--json").split(",")
    return [{k: v for k, v in row.items() if k in fields} for row in rows]

ENDPOINTS = (
    ("code-scanning/alerts", "code_scanning"),
    ("secret-scanning/alerts", "secret_scanning"),
    ("dependabot/alerts", "dependabot"),
    ("branches/main/protection", "protection"),
)

if args[:2] == ["repo", "view"]:
    emit({"nameWithOwner": "own/repo"})
elif args[0] == "api":
    path = next(a for a in args[1:] if a.startswith("repos/"))
    emit(data[next((key for part, key in ENDPOINTS if part in path), "repo")])
elif args[:2] == ["run", "list"]:
    emit(trim(data["scheduled_runs" if opt("--event") == "schedule" else "main_runs"]))
elif args[:2] == ["run", "view"]:
    if "--log" in args:
        sys.stdout.write(data["log"])
    else:
        emit({"jobs": data["jobs"][args[2]]})
elif args[:2] == ["issue", "list"]:
    emit(trim(data["issues"]))
else:
    sys.exit("fake gh: unexpected call " + " ".join(args))
"""

# The shape of `gh run view --log`: job, step, then a timestamp and the tool's own line.
_T = "UNKNOWN STEP\t2026-01-01T00:00:00.0000000Z "
PIP_AUDIT_LINE = f"Dependency Vulnerability Scan\t{_T}Found 3 known vulnerabilities in 2 packages\n"
LOG = (
    f'Dependency Vulnerability Scan\t{_T}        "vulnerabilities_found": 5,\n'
    f'Dependency Vulnerability Scan\t{_T}            "vulnerabilities_found": 2,\n'
    + PIP_AUDIT_LINE
    + f"Code Security Analysis\t{_T}\tTotal issues (by severity):\n"
    + f"Code Security Analysis\t{_T}\t\tUndefined: 0\n"
    + f"Code Security Analysis\t{_T}\t\tLow: 3\n"
    + f"Code Security Analysis\t{_T}\t\tMedium: 0\n"
    + f"Code Security Analysis\t{_T}\t\tHigh: 1\n"
    + f"Code Security Analysis\t{_T}\tTotal issues (by confidence):\n"
    + f"Code Security Analysis\t{_T}\t\tUndefined: 9\n"
)


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _alert(tool, severity):
    return {
        "tool": {"name": tool},
        "rule": {"security_severity_level": severity},
        "created_at": _iso(20),
    }


def _job(name, conclusion):
    return {"name": name, "status": "completed", "conclusion": conclusion}


def _github(head):
    """The fake GitHub state: what each query answers."""
    return {
        "code_scanning": [
            _alert("Trivy", "high"),
            _alert("Trivy", "high"),
            _alert("CodeQL", "medium"),
        ],
        "secret_scanning": [],
        "dependabot": {
            "error": "gh: Dependabot alerts are disabled for this repository. (HTTP 403)"
        },
        "scheduled_runs": [
            {"databaseId": 11, "createdAt": _iso(6), "headSha": head, "status": "completed"}
        ],
        "main_runs": [{"databaseId": 22, "headSha": head, "status": "completed"}],
        "jobs": {
            "11": [
                _job("Secret Detection", "failure"),
                _job("codeql-analysis (python)", "success"),
            ],
            "22": [_job("Code Security Analysis", "success")],
        },
        "log": LOG,
        "protection": {
            "required_status_checks": {"strict": True, "contexts": ["test", "attestation"]},
            "enforce_admins": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
        },
        "repo": {
            "visibility": "public",
            "allow_auto_merge": True,
            "security_and_analysis": {"secret_scanning": {"status": "enabled"}},
        },
        "issues": [
            {"number": 9, "title": "nine", "createdAt": _iso(3)},
            {"number": 7, "title": "seven", "createdAt": _iso(30)},
        ],
    }


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Repo:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.work = tmp_path / "work"
        self.state = tmp_path / "state"
        origin = tmp_path / "origin.git"
        _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
        _git(tmp_path, "clone", "-q", str(origin), str(self.work))
        self.commit(
            ".github/workflows/security-scan.yml",
            "run: safety check || true\nrun: pip-audit || true\nrun: bandit || true\nrun: bandit -f json || true\n",
        )
        self.commit(
            ".claude/settings.json",
            json.dumps(
                {
                    "permissions": {
                        "deny": ["Read(~/.ssh/**)", "Read(//**/.env)"],
                        "ask": ["Bash(rm -r*)"],
                    },
                    "hooks": {"Stop": [], "PreToolUse": []},
                }
            ),
        )
        bindir = tmp_path / "bin"
        bindir.mkdir()
        gh = bindir / "gh"
        gh.write_text(FAKE_GH.replace("__PYTHON__", sys.executable))
        gh.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "FAKE_GH_DATA": str(tmp_path / "data.json"),
            "SECURITY_CHECK_STATE_DIR": str(self.state),
        }
        self.env.pop("SECURITY_CHECK_DEEP_DAYS", None)

    def commit(self, path, text):
        """Add one file on main and push it, so origin/main moves."""
        target = self.work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-q", "-m", f"add {path}")
        _git(self.work, "push", "-q", "origin", "HEAD:main")

    def head(self):
        return _git(self.work, "rev-parse", "HEAD")

    def snapshots(self):
        return sorted(self.state.glob("snapshot-*.txt"))

    def run(self, github, *args):
        (self.tmp / "data.json").write_text(json.dumps(github))
        return subprocess.run(
            ["bash", str(CHECK), *args],
            cwd=self.work,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


def _changed(stdout):
    """The lines the script prints under its last heading."""
    return stdout.split("== changed since the previous run\n")[1]


def test_first_run_reports_each_section_and_records_a_baseline(repo):
    result = repo.run(_github(repo.head()))

    assert result.returncode == 0, result.stdout + result.stderr
    for line in [
        "code_scanning.open=3",
        "code_scanning.Trivy.high=2",
        "code_scanning.CodeQL.medium=1",
        "secret_scanning.open=0",
        "dependabot.open=disabled",
        "scan.scheduled.stale=no",
        "scan.scheduled.Secret_Detection=failure",
        "scan.scheduled.codeql_analysis_python_=success",
        "scan.main.Code_Security_Analysis=success",
        "report.pip_audit=Found 3 known vulnerabilities in 2 packages",
        "report.safety=5",
        "report.bandit=Undefined:0,Low:3,Medium:0,High:1",
        "report.unfailing_steps=4",
        "protection.strict=true",
        "protection.enforce_admins=true",
        "protection.required_count=2",
        "protection.required=attestation,test",
        "repo.secret_scanning=enabled",
        "harness.deny=Read(//**/.env);Read(~/.ssh/**)",
        "harness.ask_count=1",
        "harness.hooks=PreToolUse,Stop",
        "issues.priority_high=7,9",
        "first run: no previous snapshot",
        "last: none recorded",
        "due=yes (every 90 days)",
    ]:
        assert line in result.stdout.splitlines(), line
    assert _changed(result.stdout).startswith("first run: baseline recorded\n")
    assert len(repo.snapshots()) == 1


def test_an_unchanged_run_says_no_change(repo):
    github = _github(repo.head())
    repo.run(github)
    time.sleep(1.1)  # snapshot names carry a one-second timestamp

    result = repo.run(github)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"no commits since {repo.head()[:7]}" in result.stdout
    assert _changed(result.stdout).startswith("no change\n")
    assert len(repo.snapshots()) == 2


def test_a_changed_run_prints_only_what_changed(repo):
    github = _github(repo.head())
    repo.run(github)
    time.sleep(1.1)
    before = repo.head()
    repo.commit("app/security/auth.py", "x = 1\n")
    github = _github(repo.head())
    github["code_scanning"].append(_alert("Trivy", "high"))
    github["protection"]["required_status_checks"]["contexts"] = ["test"]
    github["dependabot"] = [
        {"security_advisory": {"severity": "high"}},
        {"security_advisory": {"severity": "low"}},
    ]
    github["scheduled_runs"][0]["databaseId"] = 12
    github["jobs"]["12"] = github["jobs"]["11"]

    result = repo.run(github)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        f"1 commits, {before[:7]}..{repo.head()[:7]}; files changed:\napp/security/auth.py\n"
        in result.stdout
    )
    changed = _changed(result.stdout).splitlines()
    assert set(changed[:-1]) == {
        "was: code_scanning.Trivy.high=2",
        "now: code_scanning.Trivy.high=3",
        "was: code_scanning.open=3",
        "now: code_scanning.open=4",
        "was: dependabot.open=disabled",
        "now: dependabot.open=2",
        "now: dependabot.high=1",
        "now: dependabot.low=1",
        "was: protection.required=attestation,test",
        "now: protection.required=test",
        "was: protection.required_count=2",
        "now: protection.required_count=1",
    }
    assert changed[-1].startswith("saved: ")


def test_a_failed_query_is_an_error_and_saves_no_snapshot(repo):
    github = _github(repo.head())
    repo.run(github)
    github["secret_scanning"] = {"error": "gh: Server Error (HTTP 502)"}

    result = repo.run(github)

    assert result.returncode == 1
    assert "ERROR: secret_scanning alerts failed" in result.stdout.splitlines()
    assert "secret_scanning.open" not in result.stdout
    assert _changed(result.stdout) == "not compared and not saved: a section failed\n"
    assert len(repo.snapshots()) == 1


def test_a_missing_scanner_result_line_is_an_error(repo):
    github = _github(repo.head())
    github["log"] = LOG.replace(PIP_AUDIT_LINE, "")

    result = repo.run(github)

    assert result.returncode == 1
    assert "ERROR: pip-audit result line failed" in result.stdout.splitlines()
    assert "report.safety=5" in result.stdout.splitlines()
    assert repo.snapshots() == []


@pytest.mark.parametrize(
    "runs, expected",
    [
        (
            [{"databaseId": 11, "createdAt": _iso(9), "headSha": "abc1234", "status": "completed"}],
            "scan.scheduled.stale=yes",
        ),
        (
            [{"databaseId": 11, "createdAt": _iso(8), "headSha": "abc1234", "status": "completed"}],
            "scan.scheduled.stale=no",
        ),
        ([], "scan.scheduled=none"),
    ],
)
def test_a_schedule_that_stopped_firing_is_reported(repo, runs, expected):
    github = _github(repo.head())
    github["scheduled_runs"] = runs

    result = repo.run(github)

    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout.splitlines()


def test_a_recorded_deep_audit_is_due_again_after_90_days(repo):
    github = _github(repo.head())

    recorded = repo.run(github, "--record-deep", "cso")
    assert recorded.returncode == 0, recorded.stdout + recorded.stderr
    assert repo.snapshots() == []

    fresh = repo.run(github).stdout
    assert f"last: cso on {_iso(0)[:10]} at {repo.head()[:7]} (0d ago)" in fresh
    assert "due=no (every 90 days)" in fresh.splitlines()

    old = int(time.time()) - 91 * 86400
    (repo.state / "deep-run").write_text(f"{old} 2026-01-01 abc1234 cso\n")
    assert "due=yes (every 90 days)" in repo.run(github).stdout.splitlines()


def test_an_unknown_argument_is_refused(repo):
    result = repo.run(_github(repo.head()), "--bogus")

    assert result.returncode == 2
    assert result.stdout == "usage: check.sh [--record-deep <tool>]\n"
    assert repo.snapshots() == []
