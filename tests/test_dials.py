"""#214: scripts/dials.sh on recorded `gh pr list` JSON, via a fake gh on PATH."""

import json
import os
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CREATED = "2026-10-01T10:00:00Z"


def _check(name, conclusion, completed):
    return {
        "__typename": "CheckRun",
        "name": name,
        "workflowName": "Tests",
        "conclusion": conclusion,
        "completedAt": completed,
    }


def _pr(n, merged, checks):
    return {
        "number": n,
        "title": f"pr {n}",
        "createdAt": CREATED,
        "mergedAt": merged,
        "statusCheckRollup": checks,
    }


def _run_dials(tmp_path, prs):
    (tmp_path / "prs.json").write_text(json.dumps(prs))
    fake = tmp_path / "gh"
    fake.write_text(f'#!/bin/bash\ncat "{tmp_path / "prs.json"}"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", str(REPO / "scripts/dials.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_a_red_only_pr_is_not_labelled_as_having_no_completed_check(tmp_path):
    red_only = _pr(3, "2026-10-01T11:00:00Z", [_check("test", "FAILURE", "2026-10-01T10:20:00Z")])

    out = _run_dials(tmp_path, [red_only])

    assert "no completed pre-merge check" not in out
    assert "#3  merged-before-green (no green pre-merge check)" in out
    assert "merged-on-red (1 failed: test)" in out


def test_green_to_merge_median_counts_only_prs_that_reached_all_green(tmp_path):
    clean = _pr(1, "2026-10-01T10:30:00Z", [_check("test", "SUCCESS", "2026-10-01T10:20:00Z")])
    # One check green 33m before merge, another already failed: never all-green.
    on_red = _pr(
        2,
        "2026-10-01T11:00:00Z",
        [
            _check("test", "SUCCESS", "2026-10-01T10:27:00Z"),
            _check("lint", "FAILURE", "2026-10-01T10:15:00Z"),
        ],
    )
    # A check still running at merge: never all-green either.
    early = _pr(
        4,
        "2026-10-01T12:00:00Z",
        [
            _check("test", "SUCCESS", "2026-10-01T11:00:00Z"),
            _check("lint", None, "0001-01-01T00:00:00Z"),
        ],
    )

    out = _run_dials(tmp_path, [clean, on_red, early])

    assert "median green->merge: 10m" in out
    # The per-PR timings are still shown for the excluded PRs.
    assert "#2  open->green 27m   green->merge 33m" in out
