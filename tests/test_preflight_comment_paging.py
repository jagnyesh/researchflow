"""#402: preflight's wait measure must see a PR's comments past the 100th.

`gh pr list` returns only the first 100 comments of each PR; `gh pr view` pages through all.
Runs preflight.sh against a throwaway git repo and a fake `gh` that trims its JSON to the
requested --json fields, as the real one does.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PREFLIGHT = Path(
    os.environ.get(
        "PREFLIGHT_SH",
        Path(__file__).resolve().parent.parent / ".claude/skills/plan-lanes/preflight.sh",
    )
)

FAKE_GH = r"""#!__PYTHON__
import json, os, subprocess, sys
from pathlib import Path

args = sys.argv[1:]
data = json.loads(Path(os.environ["FAKE_GH_DATA"]).read_text())
Path(os.environ["FAKE_GH_LOG"]).open("a").write(" ".join(args) + "\n")

def opt(name):
    return args[args.index(name) + 1] if name in args else None

def emit(obj):
    q = opt("-q")
    text = json.dumps(obj)
    if q is None:
        print(text)
    else:
        print(subprocess.run(["jq", "-r", q], input=text, capture_output=True, text=True, check=True).stdout, end="")

def trim(prs):
    fields = opt("--json").split(",")
    return [{k: v for k, v in pr.items() if k in fields} for pr in prs]

if args[:2] == ["repo", "view"]:
    emit({"nameWithOwner": "own/repo"})
elif args[0] == "api":
    print("true")
elif args[:2] == ["pr", "list"]:
    state = opt("--state")
    emit(trim([p["list"] for p in data["prs"] if p["state"] == state]))
elif args[:2] == ["pr", "view"]:
    pr = next(p for p in data["prs"] if p["list"]["number"] == int(args[2]))
    emit(trim([pr["full"]])[0])
else:
    emit([] if args[:2] == ["run", "list"] else 0)
"""


def _comment(created, body):
    return {
        "author": {"login": "own"},
        "authorAssociation": "OWNER",
        "createdAt": created,
        "body": body,
    }


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _pr(number, state, filler, attest_at, merged_at=None, paged=False):
    """A PR whose attestation is comment number filler+1; `list` shows only the first 100."""
    comments = [_comment(_iso(attest_at), "noise") for _ in range(filler)]
    comments.append(_comment(_iso(attest_at), "## Review attestation\n- Verdict: SHIP\n"))
    return {
        "state": state,
        "list": {
            "number": number,
            "url": f"https://github.com/own/repo/pull/{number}",
            "isDraft": False,
            "statusCheckRollup": [],
            "mergedAt": merged_at,
            "comments": comments[:100],
        },
        "full": {
            "url": f"https://github.com/own/repo/pull/{number}",
            "mergedAt": merged_at,
            "comments": comments,
        },
    }


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def run_preflight(tmp_path):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    (work / "docs").mkdir()
    (work / "scripts").mkdir()
    (work / "docs/DAILY_DEV_WORKFLOW.md").write_text(
        "Override, 2026-11-07: up to 4 lanes\nBefore opening a lane, all of these must hold:\n"
    )
    (work / "scripts/lane.sh").write_text("WIP_LIMIT=4\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "override")
    _git(work, "push", "-q", "origin", "HEAD:main")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(FAKE_GH.replace("__PYTHON__", sys.executable))
    gh.chmod(0o755)

    def run(prs):
        (tmp_path / "data.json").write_text(json.dumps({"prs": prs}))
        log = tmp_path / "gh.log"
        log.write_text("")
        env = {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "FAKE_GH_DATA": str(tmp_path / "data.json"),
            "FAKE_GH_LOG": str(log),
        }
        result = subprocess.run(
            ["bash", str(PREFLIGHT)], cwd=work, env=env, capture_output=True, text=True, timeout=60
        )
        return result, log.read_text().splitlines()

    return run


def test_attestation_after_the_100th_comment_is_found(run_preflight):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    result, calls = run_preflight(
        [
            _pr(1, "open", filler=100, attest_at=now - timedelta(minutes=30)),
            _pr(2, "open", filler=2, attest_at=now - timedelta(minutes=20)),
            _pr(
                3, "merged", filler=100, attest_at=now, merged_at=_iso(now + timedelta(minutes=10))
            ),
            _pr(4, "merged", filler=1, attest_at=now, merged_at=_iso(now + timedelta(minutes=5))),
        ]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"^#1 not green, waited 30m$", result.stdout, re.M), result.stdout
    assert re.search(r"^#2 not green, waited 20m$", result.stdout, re.M), result.stdout
    assert "no SHIP attestation" not in result.stdout
    assert "merged: 2" in result.stdout
    assert "merged without a SHIP attestation" not in result.stdout
    # only the PRs whose list hit the 100-comment cap are re-read, once per section
    assert sorted(c for c in calls if c.startswith("pr view")) == [
        "pr view 1 --json url,mergedAt,comments",
        "pr view 3 --json url,mergedAt,comments",
    ]


def test_under_the_cap_makes_no_extra_call(run_preflight):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    result, calls = run_preflight([_pr(1, "open", filler=98, attest_at=now - timedelta(minutes=5))])

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"^#1 not green, waited 5m$", result.stdout, re.M)
    assert not [c for c in calls if c.startswith("pr view")]
