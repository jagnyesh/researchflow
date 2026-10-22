"""SessionStart lane check: red main, review debt, open PRs (#196).

The hook runs for real; only `gh` is replaced, by a script on PATH that
returns JSON in the shape `gh` itself returned on 2026-10-22 (CheckRun items
from `gh pr view 195`, run rows from `gh run list --branch main`).
"""

import json
import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "SessionStart.sh"


def _check(name, conclusion="SUCCESS", status="COMPLETED"):
    return {
        "__typename": "CheckRun",
        "completedAt": "2026-10-22T21:43:30Z" if status == "COMPLETED" else None,
        "conclusion": conclusion,
        "name": name,
        "startedAt": "2026-10-22T21:43:06Z",
        "status": status,
        "workflowName": "Tests",
    }


def _pr(number, checks, draft=False):
    return {
        "number": number,
        "title": f"fix: change {number}",
        "headRefName": f"fix/{number}-slug",
        "isDraft": draft,
        "statusCheckRollup": checks,
    }


def _run(workflow, conclusion, created, sha="654145ebecc263e2baea82379247587dfac5422c"):
    return {
        "workflowName": workflow,
        "conclusion": conclusion,
        "status": "completed",
        "createdAt": created,
        "headSha": sha,
    }


GREEN_MAIN = [
    _run("Tests", "success", "2026-10-22T22:05:34Z"),
    _run("Security Scanning", "success", "2026-10-22T22:05:34Z"),
]


def _lane_lines(tmp_path, prs=None, runs=None, gh_body=None):
    """Run the hook with a fake `gh`; return only the lane-check output."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "prs.json").write_text(json.dumps(prs if prs is not None else []))
    (tmp_path / "runs.json").write_text(json.dumps(runs if runs is not None else GREEN_MAIN))
    gh = bin_dir / "gh"
    gh.write_text(
        gh_body
        or (
            "#!/bin/bash\n"
            f'case "$1 $2" in\n'
            f'  "pr list") cat "{tmp_path}/prs.json" ;;\n'
            f'  "run list") cat "{tmp_path}/runs.json" ;;\n'
            "  *) exit 2 ;;\n"
            "esac\n"
        )
    )
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    out = subprocess.run(
        ["bash", str(HOOK)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line.startswith("🚦") or "lane check" in line]


def test_all_clear_prints_nothing(tmp_path):
    assert _lane_lines(tmp_path) == []


def test_latest_failed_run_on_main_is_red(tmp_path):
    runs = [
        _run("Tests", "failure", "2026-10-22T21:27:00Z", sha="ae1e80f" + "0" * 33),
        _run("Tests", "success", "2026-10-22T20:48:00Z"),
        _run("Security Scanning", "success", "2026-10-22T21:27:00Z"),
    ]
    assert _lane_lines(tmp_path, runs=runs) == [
        "🚦 main CI red: Tests @ ae1e80f — §10: one lane until green"
    ]


def test_failure_fixed_by_a_later_run_is_not_red(tmp_path):
    runs = [
        _run("Tests", "success", "2026-10-22T22:05:34Z"),
        _run("Tests", "failure", "2026-10-22T21:27:00Z"),
    ]
    assert _lane_lines(tmp_path, runs=runs) == []


def test_two_green_prs_trip_the_review_debt_rule(tmp_path):
    green = [_check("test (ubuntu-latest, 3.11)"), _check("Container Security Scan", "SKIPPED")]
    prs = [_pr(195, green), _pr(193, green)]
    assert _lane_lines(tmp_path, prs=prs) == [
        "🚦 2 PRs await your decision (#195, #193) — §10: no new lane at ≥2",
        "🚦 In flight: #195 [fix/195-slug] fix: change 195",
        "🚦 In flight: #193 [fix/193-slug] fix: change 193",
    ]


def test_drafts_pending_and_failing_prs_are_not_awaiting_a_decision(tmp_path):
    prs = [
        _pr(1, [_check("test")]),
        _pr(2, [_check("test")], draft=True),
        _pr(3, [_check("test", conclusion="", status="IN_PROGRESS")]),
        _pr(4, [_check("test", conclusion="FAILURE")]),
        _pr(5, []),
    ]
    lines = _lane_lines(tmp_path, prs=prs)
    assert not any("await your decision" in line for line in lines)
    assert len([line for line in lines if line.startswith("🚦 In flight")]) == 5


def test_gh_failure_says_skipped_instead_of_staying_silent(tmp_path):
    lines = _lane_lines(tmp_path, gh_body="#!/bin/bash\nexit 1\n")
    assert lines == ["ℹ️  lane check skipped: gh failed (offline, unauthenticated, or timed out)"]


def test_unexpected_gh_output_says_skipped(tmp_path):
    lines = _lane_lines(tmp_path, gh_body="#!/bin/bash\necho 'not json'\n")
    assert lines == ["ℹ️  lane check skipped: unexpected gh output"]


def test_banner_reports_the_branch_of_the_session_cwd(tmp_path):
    """A worktree session runs the hook from the original checkout; the
    banner's branch must come from the stdin `cwd`, not the hook's location."""
    session = tmp_path / "worktree"
    subprocess.run(["git", "init", "-q", "-b", "claude/some-session", str(session)], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text("#!/bin/bash\nexit 1\n")
    (bin_dir / "gh").chmod(0o755)
    out = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(session)}),
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
        timeout=30,
        check=True,
    ).stdout
    banner = next(line for line in out.splitlines() if line.startswith("📋"))
    assert banner.endswith("| branch: claude/some-session")
