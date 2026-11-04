"""#198: lane.sh counts lanes by branch, wherever the worktree lives.

Runs against a throwaway git repo (sandbox-first: lane.sh mutates worktrees).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

LANE_SH = Path(__file__).resolve().parent.parent / "scripts/lane.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(
        root,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.org",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "init",
    )
    (root / "scripts").mkdir()
    shutil.copy(LANE_SH, root / "scripts/lane.sh")
    return root


def _wip(repo) -> str:
    out = subprocess.run(
        ["bash", "scripts/lane.sh", "list"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    return next(line for line in out.splitlines() if line.startswith("WIP:"))


def test_a_native_claude_worktree_on_an_issue_branch_counts(repo):
    _git(
        repo,
        "worktree",
        "add",
        "-q",
        "-b",
        "feat/196-session-lane-check",
        ".claude/worktrees/status-check-dc924f",
    )

    assert _wip(repo).startswith("WIP: 1/2")


def test_detached_and_non_issue_worktrees_do_not_count(repo, tmp_path):
    _git(repo, "worktree", "add", "-q", "--detach", ".claude/worktrees/stale-abc123")
    _git(repo, "worktree", "add", "-q", "-b", "chore/notes", str(tmp_path / "scratch"))

    assert _wip(repo).startswith("WIP: 0/2")


def test_open_refuses_at_two_lanes_wherever_they_live(repo, tmp_path):
    _git(repo, "worktree", "add", "-q", "-b", "fix/10-a", ".claude/worktrees/x1")
    _git(repo, "worktree", "add", "-q", "-b", "feat/11-b", str(tmp_path / "elsewhere"))

    result = subprocess.run(
        ["bash", "scripts/lane.sh", "open", "12", "--no-deps"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "WIP limit reached (2/2" in result.stderr + result.stdout


def test_the_main_checkout_does_not_count_even_on_an_issue_branch(repo):
    _git(repo, "checkout", "-q", "-b", "fix/277-gender")

    assert _wip(repo).startswith("WIP: 0/2")
