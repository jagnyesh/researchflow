"""#493: check.sh reports GitHub-side security state and what changed since the last run.

Runs the script against a throwaway git repo and a fake `gh` that trims its JSON to the
requested --json fields and applies -q with jq, as the real one does. Every value here is
made up; none describes the real repo.
"""

import json
import os
import re
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
if os.environ.get("FAKE_GH_STDERR"):
    print("* Request to https://api.github.com\n* Request took 1ms", file=sys.stderr)

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

def rows(key):
    value = data[key]
    if isinstance(value, dict):
        emit(value)
    fields, status = opt("--json").split(","), opt("--status")
    return [{k: v for k, v in row.items() if k in fields} for row in value if status in (None, row.get("status"))]

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
    emit(rows("scheduled_runs" if opt("--event") == "schedule" else "main_runs"))
elif args[:2] == ["run", "view"]:
    if "--log" in args:
        if data["log"] is None:
            sys.exit("gh: log not found")
        sys.stdout.write(data["log"])
    else:
        jobs = data["jobs"][args[2]]
        emit(jobs if isinstance(jobs, dict) else {"jobs": jobs})
elif args[:2] == ["issue", "list"]:
    emit(rows("issues"))
else:
    sys.exit("fake gh: unexpected call " + " ".join(args))
"""

WORKFLOW = ".github/workflows/security-scan.yml"
SETTINGS = ".claude/settings.json"
HOOK = ".claude/hooks/stop.sh"
ERROR = {"error": "gh: Server Error (HTTP 502)"}

# The shape of `gh run view --log`: job, step, then a timestamp and the tool's own line.
_T = "UNKNOWN STEP\t2026-01-01T00:00:00.0000000Z "
SAFETY_LINES = (
    f'Dependency Vulnerability Scan\t{_T}        "vulnerabilities_found": 5,\n'
    f'Dependency Vulnerability Scan\t{_T}            "vulnerabilities_found": 2,\n'
)
PIP_AUDIT_LINE = f"Dependency Vulnerability Scan\t{_T}Found 3 known vulnerabilities in 2 packages\n"
BANDIT_HEAD = f"Code Security Analysis\t{_T}\tTotal issues (by severity):\n"
LOG = (
    SAFETY_LINES
    + PIP_AUDIT_LINE
    + BANDIT_HEAD
    + f"Code Security Analysis\t{_T}\t\tUndefined: 0\n"
    + f"Code Security Analysis\t{_T}\t\tLow: 3\n"
    + f"Code Security Analysis\t{_T}\t\tMedium: 0\n"
    + f"Code Security Analysis\t{_T}\t\tHigh: 1\n"
    + f"Code Security Analysis\t{_T}\tTotal issues (by confidence):\n"
    + f"Code Security Analysis\t{_T}\t\tUndefined: 9\n"
)


def _settings(ask="Bash(rm -r*)", **permissions):
    return json.dumps(
        {
            "permissions": {
                "deny": ["Read(~/.ssh/**)", "Read(//**/.env)"],
                "ask": [ask],
                **permissions,
            },
            "hooks": {"Stop": [{"command": HOOK}], "PreToolUse": []},
        }
    )


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _alert(tool, severity, rule_severity=None):
    return {
        "tool": {"name": tool},
        "rule": {"security_severity_level": severity, "severity": rule_severity},
        "created_at": _iso(20),
    }


def _job(name, conclusion, status="completed"):
    return {"name": name, "status": status, "conclusion": conclusion}


def _run(run_id, days_ago, head="abc1234", status="completed"):
    return {"databaseId": run_id, "createdAt": _iso(days_ago), "headSha": head, "status": status}


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
        "scheduled_runs": [_run(11, 6, head)],
        "main_runs": [_run(22, 0, head)],
        "jobs": {
            "11": [
                _job("Secret Detection", "failure"),
                _job("codeql-analysis (python)", "success"),
            ],
            "22": [_job("Code Security Analysis", "success")],
        },
        "log": LOG,
        "protection": {
            "url": "https://api.github.com/repos/own/repo/branches/main/protection",
            "required_status_checks": {
                "strict": True,
                "contexts": ["test", "attestation"],
                "checks": [
                    {"context": "test", "app_id": 15368},
                    {"context": "attestation", "app_id": 15368},
                ],
            },
            "enforce_admins": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
            "required_signatures": {"enabled": True},
            "required_pull_request_reviews": {"required_approving_review_count": 1},
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
    """An origin, an `author` clone that pushes to it, and `work`, where the script runs.

    `work` sees a new commit only when the script fetches it.
    """

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.state = tmp_path / "state"
        origin = tmp_path / "origin.git"
        _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
        self.author = tmp_path / "author"
        _git(tmp_path, "clone", "-q", str(origin), str(self.author))
        steps = "run: safety check || true\nrun: pip-audit || true\nrun: bandit || true\nrun: bandit -f json || true\n"
        self.commit({WORKFLOW: steps, SETTINGS: _settings(), HOOK: "exit 0\n"})
        self.work = tmp_path / "work"
        _git(tmp_path, "clone", "-q", str(origin), str(self.work))
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
        for name in ("SECURITY_CHECK_DEEP_DAYS", "FAKE_GH_STDERR"):
            self.env.pop(name, None)

    def commit(self, files):
        """Write (or, for None, delete) files on main and push, so origin moves."""
        for path, text in files.items():
            target = self.author / path
            if text is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        _git(self.author, "add", "-A")
        _git(self.author, "commit", "-q", "-m", f"change {next(iter(files))}")
        _git(self.author, "push", "-q", "origin", "HEAD:main")

    def head(self):
        return _git(self.author, "rev-parse", "HEAD")

    def snapshots(self):
        return sorted(self.state.glob("snapshot-*.txt"))

    def run(self, github, *args, **env):
        if self.snapshots():
            time.sleep(1.05)  # snapshot names carry a one-second timestamp
        (self.tmp / "data.json").write_text(json.dumps(github))
        return subprocess.run(
            ["bash", str(CHECK), *args],
            cwd=self.work,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
        )


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


def _changed(result):
    """The lines under the script's last heading, without the "saved:" line."""
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.split("== changed since the previous run\n")[1].splitlines()
    assert lines[-1].startswith("saved: ")
    return lines[:-1]


def _keys(changed):
    return {line.split(": ", 1)[1].split("=", 1)[0] for line in changed}


def test_first_run_reports_each_section_and_records_a_baseline(repo):
    result = repo.run(_github(repo.head()))

    lines = result.stdout.splitlines()
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
        "protection.required_count=2",
        "protection.required=attestation@15368,test@15368",
        "protection.enforce_admins=true",
        "protection.force_pushes=false",
        "protection.deletions=false",
        "protection.signatures=true",
        "protection.required_reviews=1",
        "repo.visibility=public",
        "repo.allow_auto_merge=true",
        "repo.secret_scanning=enabled",
        "harness.deny=Read(//**/.env);Read(~/.ssh/**)",
        "harness.allow=",
        "harness.default_mode=unset",
        "harness.ask_count=1",
        "harness.hooks=PreToolUse,Stop",
        "issues.priority_high=7,9",
        "first run: no previous snapshot",
        "last: none recorded",
        "due=yes (every 90 days)",
    ]:
        assert line in lines, line
    for pattern in [
        r"protection\.digest=[0-9a-f]{12}",
        r"harness\.settings_blob=[0-9a-f]{12}",
        r"harness\.hooks_tree=[0-9a-f]{12}",
    ]:
        assert any(re.fullmatch(pattern, line) for line in lines), pattern
    assert _changed(result) == ["first run: baseline recorded"]
    assert len(repo.snapshots()) == 1


def test_an_unchanged_run_says_no_change(repo):
    github = _github(repo.head())
    repo.run(github)

    result = repo.run(github)

    assert _changed(result) == ["no change"]
    assert f"no commits since {repo.head()[:7]}" in result.stdout.splitlines()
    assert len(repo.snapshots()) == 2


def test_a_changed_run_prints_only_what_changed(repo):
    repo.run(_github(repo.head()))
    before = repo.head()
    repo.commit({"app/security/auth.py": "x = 1\n"})
    after = repo.head()
    github = _github(after)
    github["code_scanning"].append(_alert("Trivy", "high"))
    github["dependabot"] = [
        {"security_advisory": {"severity": "high"}},
        {"security_advisory": {"severity": "low"}},
    ]
    github["scheduled_runs"] = [_run(12, 1, after)]
    github["jobs"]["12"] = github["jobs"]["11"]

    result = repo.run(github)

    assert set(_changed(result)) == {
        "was: code_scanning.Trivy.high=2",
        "now: code_scanning.Trivy.high=3",
        "was: code_scanning.open=3",
        "now: code_scanning.open=4",
        "was: dependabot.open=disabled",
        "now: dependabot.open=2",
        "now: dependabot.high=1",
        "now: dependabot.low=1",
    }
    expected = (
        f"1 commits, {before[:7]}..{after[:7]}:\n{after[:7]} change app/security/auth.py\n"
        "1 files changed:\napp/security/auth.py\n== deep audit\n"
    )
    assert expected in result.stdout


def test_the_newest_snapshot_is_the_one_compared(repo):
    github = _github(repo.head())
    repo.run(github)
    github["code_scanning"].append(_alert("Trivy", "low"))
    repo.run(github)

    assert _changed(repo.run(github)) == ["no change"]


def test_a_failed_query_is_an_error_and_saves_no_snapshot(repo):
    github = _github(repo.head())
    repo.run(github)
    github["secret_scanning"] = ERROR

    result = repo.run(github)

    assert result.returncode == 1
    assert "ERROR: secret_scanning alerts failed" in result.stdout.splitlines()
    assert "secret_scanning.open" not in result.stdout
    assert result.stdout.endswith(
        "== changed since the previous run\nnot compared and not saved: a section failed\n"
    )
    assert len(repo.snapshots()) == 1


def _set(key, value):
    return lambda repo, github: github.__setitem__(key, value)


def _set_job(run_id):
    return lambda repo, github: github["jobs"].__setitem__(run_id, ERROR)


def _commit(files):
    return lambda repo, github: repo.commit(files)


@pytest.mark.parametrize(
    "break_it, error",
    [
        (_set("code_scanning", ERROR), "code_scanning alerts"),
        (_set("dependabot", ERROR), "dependabot alerts"),
        (_set("scheduled_runs", ERROR), "scheduled scan lookup"),
        (_set_job("11"), "scheduled scan jobs"),
        (_set("main_runs", []), "main scan lookup"),
        (_set_job("22"), "main scan jobs"),
        (_set("log", None), "scan log download"),
        (_set("log", LOG.replace(PIP_AUDIT_LINE, "")), "pip-audit result line"),
        (_set("log", LOG.replace(SAFETY_LINES, "")), "safety result line"),
        (_set("log", LOG.replace(BANDIT_HEAD, "")), "bandit result lines"),
        (_commit({WORKFLOW: None}), "security-scan.yml read"),
        (_set("protection", ERROR), "branch protection"),
        (_set("protection", [1]), "branch protection"),
        (_set("repo", ERROR), "repo settings"),
        (_set("repo", [1]), "repo settings"),
        (_commit({SETTINGS: None}), "settings.json read"),
        (_commit({SETTINGS: "{not json"}), "settings.json read"),
        (_set("issues", ERROR), "issue list"),
    ],
)
def test_each_failed_section_is_an_error_and_saves_no_snapshot(repo, break_it, error):
    github = _github(repo.head())
    break_it(repo, github)

    result = repo.run(github)

    assert result.returncode == 1
    assert f"ERROR: {error} failed" in result.stdout.splitlines()
    assert repo.snapshots() == []


def test_a_failed_fetch_is_an_error_and_saves_no_snapshot(repo):
    _git(repo.work, "remote", "set-url", "origin", str(repo.tmp / "missing.git"))

    result = repo.run(_github(repo.head()))

    assert result.returncode == 1
    assert "ERROR: fetch of origin/main (it may be stale) failed" in result.stdout.splitlines()
    assert repo.snapshots() == []


def test_an_unprotected_main_is_recorded_as_a_state(repo):
    github = _github(repo.head())
    repo.run(github)
    github["protection"] = {"error": "gh: Branch not protected (HTTP 404)"}

    changed = _changed(repo.run(github))

    assert "now: protection=none" in changed
    assert "was: protection.strict=true" in changed
    assert len(repo.snapshots()) == 2


def test_protection_changes_outside_the_itemized_lines_still_show(repo):
    github = _github(repo.head())
    repo.run(github)
    github["protection"]["required_status_checks"]["checks"][1]["app_id"] = None
    del github["protection"]["required_pull_request_reviews"]
    github["protection"]["required_signatures"]["enabled"] = False

    itemized = _changed(repo.run(github))

    assert {
        "was: protection.required=attestation@15368,test@15368",
        "now: protection.required=attestation,test@15368",
        "was: protection.required_reviews=1",
        "now: protection.required_reviews=none",
        "was: protection.signatures=true",
        "now: protection.signatures=false",
    } <= set(itemized)
    assert _keys(itemized) == {
        "protection.required",
        "protection.required_reviews",
        "protection.signatures",
        "protection.digest",
    }

    github["protection"]["required_linear_history"] = {"enabled": True}
    assert _keys(_changed(repo.run(github))) == {"protection.digest"}


def test_harness_changes_outside_the_itemized_lines_still_show(repo):
    github = _github(repo.head())
    repo.run(github)
    repo.commit({SETTINGS: _settings(ask="Bash(git push -f*)"), HOOK: "exit 1\n"})

    swapped = _changed(repo.run(github))

    assert _keys(swapped) == {"harness.settings_blob", "harness.hooks_tree"}

    repo.commit({SETTINGS: _settings(allow=["Bash(*)"], defaultMode="acceptEdits")})
    widened = _changed(repo.run(github))
    assert "now: harness.allow=Bash(*)" in widened
    assert "now: harness.default_mode=acceptEdits" in widened
    assert _keys(widened) == {"harness.allow", "harness.default_mode", "harness.settings_blob"}


def test_stderr_lines_from_gh_are_not_counted_as_alerts(repo):
    result = repo.run(_github(repo.head()), FAKE_GH_STDERR="1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "secret_scanning.open=0" in result.stdout.splitlines()
    assert "code_scanning.open=3" in result.stdout.splitlines()


def test_an_alert_without_a_security_severity_uses_the_rule_severity(repo):
    github = _github(repo.head())
    github["code_scanning"] = [_alert("CodeQL", None, "warning"), _alert("Code QL", None)]

    lines = repo.run(github).stdout.splitlines()

    assert "code_scanning.CodeQL.warning=1" in lines
    assert "code_scanning.Code_QL.none=1" in lines


def test_an_unfinished_job_prints_its_status(repo):
    github = _github(repo.head())
    github["jobs"]["22"] = [_job("Code Security Analysis", "", status="in_progress")]

    result = repo.run(github)

    assert "scan.main.Code_Security_Analysis=in_progress" in result.stdout.splitlines()


def test_a_run_in_progress_is_passed_over_for_the_latest_completed_one(repo):
    github = _github(repo.head())
    github["scheduled_runs"] = [_run(13, 0, status="in_progress"), _run(11, 6)]
    github["main_runs"] = [_run(23, 0, status="in_progress"), _run(22, 0, repo.head())]

    result = repo.run(github)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"# scan.scheduled.run=11 {_iso(6)[:10]} abc1234 (6d ago)" in result.stdout.splitlines()
    assert f"# scan.main.run=22 {repo.head()[:7]}" in result.stdout.splitlines()


@pytest.mark.parametrize(
    "runs, expected",
    [
        ([_run(11, 9)], "scan.scheduled.stale=yes"),
        ([_run(11, 8)], "scan.scheduled.stale=no"),
        ([], "scan.scheduled=none"),
    ],
)
def test_a_schedule_that_stopped_firing_is_reported(repo, runs, expected):
    github = _github(repo.head())
    github["scheduled_runs"] = runs

    result = repo.run(github)

    assert result.returncode == 0, result.stdout + result.stderr
    assert expected in result.stdout.splitlines()


def test_a_scan_on_an_older_commit_is_noted(repo):
    github = _github(repo.head())
    github["main_runs"] = [_run(22, 0, "f" * 40)]

    result = repo.run(github)

    assert (
        f"NOTE: the latest completed scan ran on fffffff; main is {repo.head()[:7]}"
        in result.stdout.splitlines()
    )


def test_a_rewritten_main_is_reported(repo):
    repo.state.mkdir()
    (repo.state / "snapshot-20200101T000000Z-0000000.txt").write_text(f"# main={'0' * 40}\n")

    result = repo.run(_github(repo.head()))

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "REWRITTEN: the previous snapshot's commit 0000000 is not an ancestor of main"
        in result.stdout.splitlines()
    )


def test_a_long_file_list_is_cut_and_the_rest_counted(repo):
    github = _github(repo.head())
    repo.run(github)
    repo.commit({f"docs/f{i:03}.md": "x\n" for i in range(305)})

    result = repo.run(github)

    listed = result.stdout.split("305 files changed:\n")[1].split("== deep audit\n")[0].splitlines()
    assert listed[:300] == [f"docs/f{i:03}.md" for i in range(300)]
    assert listed[300:] == ["... and 5 more files"]


def test_a_recorded_deep_audit_is_due_again_after_90_days(repo):
    github = _github(repo.head())

    recorded = repo.run(github, "--record-deep", "cso")
    assert recorded.returncode == 0, recorded.stdout + recorded.stderr
    assert repo.snapshots() == []

    fresh = repo.run(github).stdout.splitlines()
    assert any(
        re.fullmatch(rf"last: cso on \d{{4}}-\d\d-\d\d at {repo.head()[:7]} \(0d ago\)", line)
        for line in fresh
    )
    assert "due=no (every 90 days)" in fresh

    (repo.state / "deep-run").write_text(
        f"{int(time.time()) - 90 * 86400 - 60} 2026-01-01 abc1234 cso\n"
    )
    assert "due=no (every 90 days)" in repo.run(github).stdout.splitlines()
    (repo.state / "deep-run").write_text(
        f"{int(time.time()) - 91 * 86400 - 60} 2026-01-01 abc1234 cso\n"
    )
    assert "due=yes (every 90 days)" in repo.run(github).stdout.splitlines()


@pytest.mark.parametrize(
    "args", [("--record-deep",), ("--record-deep", "cso", "extra"), ("--bogus",)]
)
def test_wrong_arguments_are_refused(repo, args):
    result = repo.run(_github(repo.head()), *args)

    assert result.returncode == 2
    assert result.stdout.startswith("usage: check.sh ")
    assert repo.snapshots() == []
    assert not (repo.state / "deep-run").exists()


def test_a_deep_audit_is_not_recorded_when_the_fetch_fails(repo):
    _git(repo.work, "remote", "set-url", "origin", str(repo.tmp / "missing.git"))

    result = repo.run(_github(repo.head()), "--record-deep", "cso")

    assert result.returncode == 1
    assert "not recorded: origin/main could not be fetched" in result.stdout.splitlines()
    assert not (repo.state / "deep-run").exists()
