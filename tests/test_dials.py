"""#214: scripts/dials.sh on recorded `gh pr list` JSON, via a fake gh on PATH."""

import csv
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
        "body": "- Risk tier: medium. Paths: x\n",
        "closingIssuesReferences": [],
    }


# `pr list` and `issue list` return only the fields --json named, as the real gh does; `pr view`
# answers the attestation reader (-q) with MISSING and a plain call with no comments.
FAKE_GH = """#!/bin/bash
fields=""
for ((i = 1; i <= $#; i++)); do
  [ "${!i}" = --json ] && { j=$((i + 1)); fields=${!j}; }
done
trim='.[] | . as $d | reduce ($f|split(",")[]) as $k ({}; .[$k] = $d[$k])'
case "$1 $2" in
  "pr list") jq -c --arg f "$fields" "$trim" "$FAKE_PRS" | jq -s . ;;
  "issue list") echo '[]' ;;
  "pr view") case "$*" in *" -q "*) echo MISSING ;; *) echo '{"url":"https://github.com/o/r/pull/1","comments":[]}' ;; esac ;;
  api) echo '[]' ;;
  *) echo "fake gh: unsupported: $*" >&2; exit 64 ;;
esac
"""


def _run_dials(tmp_path, prs):
    (tmp_path / "prs.json").write_text(json.dumps(prs))
    for name, text in (("gh", FAKE_GH), ("git", "#!/bin/bash\n:\n")):
        fake = tmp_path / name
        fake.write_text(text)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_PRS": str(tmp_path / "prs.json"),
        "REVIEW_METRICS_OUT": str(tmp_path / "review_metrics.csv"),
    }
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


def test_dials_prints_a_row_for_every_tier_and_the_issue_flow(tmp_path):
    clean = _pr(1, "2026-10-01T10:30:00Z", [_check("test", "SUCCESS", "2026-10-01T10:20:00Z")])

    out = _run_dials(tmp_path, [clean])

    lines = out.splitlines()
    for tier in ("low", "medium", "high", "unknown"):
        assert any(ln.split()[:1] == [tier] for ln in lines), tier
    medium = next(ln for ln in lines if ln.split()[:1] == ["medium"])
    assert medium.split()[1] == "1"  # the one merged PR carries `Risk tier: medium`
    assert "left out" in out
    assert "== issue flow, ISO weeks ==" in out
    assert len(list(csv.DictReader((tmp_path / "review_metrics.csv").open()))) == 1
