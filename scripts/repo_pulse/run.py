"""Repo Pulse export (#541): the CSVs behind the Repo Pulse dashboard, from git and the GitHub REST API.

    python3 scripts/repo_pulse/run.py [--repo owner/name] [--clone DIR] [--local FILE] [--out DIR]

--clone   a full (non-shallow) clone whose origin is the repo; default: the checkout this script is in.
          The script fetches origin/main and refs/pull/*/head into it (the PR heads give merge_latency's
          base_behind, §3's up-to-date rule as measured).
--local   local.json from local.py, run in your own checkout (worktrees, local main against origin/main).
          Default: run local.py on --clone now. Run it where your worktrees are, or lanes_now.csv is empty.
--out     default logs/repo_pulse (gitignored). Writes <out>/raw/*.json and <out>/*.csv.

Needs `gh` authenticated for the repo's REST API; it never uses GraphQL. Each CSV's columns and rules are in
the docstrings of export.py (13 files) and review.py (review_metrics.csv, issue_flow.csv), and the dashboard's
Sources panel describes each one.
"""

import argparse
import os
import re
import shutil
import subprocess  # nosec B404 - fixed git/gh argument lists, no shell
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def sh(*a, **kw):
    return subprocess.run(
        list(a), check=True, text=True, **kw
    )  # nosec B603 B607 - fixed git/gh argument lists, no shell


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo")
    ap.add_argument("--clone", default=os.path.abspath(os.path.join(HERE, "..", "..")))
    ap.add_argument("--local")
    ap.add_argument("--out", default="logs/repo_pulse")
    a = ap.parse_args()
    repo = a.repo
    if not repo:
        url = sh(
            "git", "-C", a.clone, "remote", "get-url", "origin", capture_output=True
        ).stdout.strip()
        repo = re.sub(r"(\.git)?$", "", re.split(r"github\.com[:/]", url)[-1])
    env = {**os.environ, "REPO_PULSE_REPO": repo}
    raw = os.path.join(a.out, "raw")
    os.makedirs(raw, exist_ok=True)

    sh(
        "git",
        "-C",
        a.clone,
        "fetch",
        "-q",
        "origin",
        "+refs/heads/main:refs/remotes/origin/main",
        "+refs/pull/*/head:refs/remotes/pr/*",
    )
    with open(os.path.join(raw, "exported_at"), "w") as f:
        f.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"))
    if a.local:
        shutil.copyfile(a.local, os.path.join(raw, "local.json"))
    else:
        with open(os.path.join(raw, "local.json"), "w") as f:
            sh(sys.executable, os.path.join(HERE, "local.py"), a.clone, stdout=f)
    sh(sys.executable, os.path.join(HERE, "fetch.py"), raw, env=env)
    sh(sys.executable, os.path.join(HERE, "export.py"), a.clone, raw, a.out, env=env)
    sh(sys.executable, os.path.join(HERE, "review.py"), a.clone, raw, a.out, env=env)


if __name__ == "__main__":
    main()
