"""The part of the Repo Pulse export only your own checkout knows (#541): its worktrees, how far local main is from
origin/main, and its untracked files. Prints local.json to stdout. Read-only: it runs no fetch, so origin/main is
whatever your checkout last fetched.

usage: python3 scripts/repo_pulse/local.py [checkout] > logs/repo_pulse/raw/local.json

A worktree folder that no longer exists makes the worktree stop counting as a lane. When the checkout is mounted
at another path (a VM, a container), a path under the checkout's own .claude/worktrees/ is looked up there instead.
"""

import json
import os
import subprocess  # nosec B404 - fixed git/gh argument lists, no shell
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pulse import parse_worktrees, worktree_labels  # noqa: E402

top = sys.argv[1] if len(sys.argv) > 1 else "."


def git(*a):
    return subprocess.run(  # nosec B603 B607 - fixed git/gh argument lists, no shell
        ["git", "-C", top, *a], capture_output=True, text=True, check=True
    ).stdout.strip()


def count(rng):
    return int(git("rev-list", "--count", rng))


def folder_exists(path, here):
    if os.path.isdir(path):
        return True
    marker = "/.claude/worktrees/"
    return marker in path and os.path.isdir(here + path[path.index(marker) :])


here = git("rev-parse", "--show-toplevel")
trees = parse_worktrees(git("worktree", "list", "--porcelain"))[
    1:
]  # the first entry is the main checkout
out = {
    "behind": count("main..origin/main"),
    "ahead": count("origin/main..main"),
    "untracked": sum(
        1 for line in git("status", "--porcelain").splitlines() if line.startswith("??")
    ),
    "worktrees": [
        {
            "label": label,
            "head": t["head"],
            "ahead": count(f"origin/main..{t['head']}"),
            "exists": folder_exists(t["path"], here),
        }
        for t, label in zip(trees, worktree_labels(trees))
    ],
}
json.dump(out, sys.stdout, indent=1)
print()
