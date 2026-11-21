"""Unit tests for scripts/repo_pulse/pulse.py, the Repo Pulse exporter's pure helpers (#541)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "repo_pulse"))
from pulse import (
    area,
    ext,
    lane_status,
    parse_worktrees,
    split_rename,
    worktree_labels,
)  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "path, want",
    [
        ("app/main.py", "app"),
        ("tests/conftest.py", "tests"),
        ("scripts/dials.sh", "scripts"),
        (".github/workflows/tests.yml", "ci"),
        ("docs/DAILY_DEV_WORKFLOW.md", "docs"),
        ("CLAUDE.md", "docs"),  # root-level markdown counts as docs
        ("config/README.md", "other"),  # markdown below the root does not
        ("pyproject.toml", "other"),
    ],
)
def test_area(path, want):
    assert area(path) == want


@pytest.mark.parametrize(
    "path, want",
    [
        ("app/main.py", "py"),
        ("Makefile", "(none)"),
        (".gitignore", "gitignore"),
        ("config/.env.example", "example"),
    ],
)
def test_ext(path, want):
    assert ext(path) == want


@pytest.mark.parametrize(
    "numstat, want",
    [
        ("app/a.py", (None, "app/a.py")),
        ("app/{old => new}/a.py", ("app/old/a.py", "app/new/a.py")),
        ("{app => tests}/a.py", ("app/a.py", "tests/a.py")),
        ("docs/{ => archive}/a.md", ("docs/a.md", "docs/archive/a.md")),
        ("old.md => docs/new.md", ("old.md", "docs/new.md")),
    ],
)
def test_split_rename(numstat, want):
    assert split_rename(numstat) == want


@pytest.mark.parametrize(
    "branch, ahead, pr_state, exists, want",
    [
        ("fix/1-x", 3, "merged", True, ("no", "PR merged")),
        ("fix/1-x", 3, "closed", True, ("no", "PR closed")),
        ("fix/1-x", 3, "none", False, ("no", "folder gone")),
        ("fix/1-x", 3, "open", True, ("yes", "open PR")),
        ("(detached at abc1234)", 0, "none", True, ("no", "detached, no commits")),
        ("(detached at abc1234)", 2, "none", True, ("yes", "commits, no PR yet")),
        ("feat/2-y", 0, "none", True, ("yes", "no commits yet")),
    ],
)
def test_lane_status_follows_section_3(branch, ahead, pr_state, exists, want):
    assert lane_status(branch, ahead, pr_state, exists) == want


PORCELAIN = """worktree /r
HEAD 1111111aaaa
branch refs/heads/main

worktree /r/.claude/worktrees/a
HEAD 2222222bbbb
detached

worktree /tmp/x/wt-one
HEAD 3333333cccc
detached

worktree /tmp/x/wt-two
HEAD 3333333cccc
detached

worktree /r/.claude/worktrees/b
HEAD 4444444dddd
branch refs/heads/feat/9-z
"""


def test_worktrees_parse_and_label_uniquely():
    trees = parse_worktrees(PORCELAIN)
    assert [t["path"] for t in trees] == [
        "/r",
        "/r/.claude/worktrees/a",
        "/tmp/x/wt-one",
        "/tmp/x/wt-two",
        "/r/.claude/worktrees/b",
    ]
    assert trees[0]["branch"] == "main" and trees[1]["branch"] is None
    labels = worktree_labels(trees[1:])
    assert labels == [
        "(detached at 2222222)",
        "(detached at 3333333, wt-one)",
        "(detached at 3333333, wt-two)",
        "feat/9-z",
    ]
    assert len(set(labels)) == len(labels)
