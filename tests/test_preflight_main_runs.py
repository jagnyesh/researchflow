"""#486: preflight's main-head pipeline check counts push runs only.

Comment-triggered `Attestation` runs attach to main's head and end `cancelled` or
`skipped`; they must not read as a red main. Fake `gh` honors --event as the real one does.
"""

import json
import os
import subprocess
import sys

import pytest

from tests.test_preflight_comment_paging import FAKE_GH, PREFLIGHT, _git

RUN_LIST_FAKE = FAKE_GH.replace(
    'emit([] if args[:2] == ["run", "list"] else 0)',
    'emit([r for r in data.get("runs", []) if opt("--event") in (None, r["event"])]'
    ' if args[:2] == ["run", "list"] else 0)',
)


def _run(tmp_path, runs):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    (work / "f").write_text("x")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "c")
    _git(work, "push", "-q", "origin", "HEAD:main")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(RUN_LIST_FAKE.replace("__PYTHON__", sys.executable))
    gh.chmod(0o755)
    (tmp_path / "data.json").write_text(json.dumps({"prs": [], "runs": runs}))
    (tmp_path / "gh.log").write_text("")
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE_GH_DATA": str(tmp_path / "data.json"),
        "FAKE_GH_LOG": str(tmp_path / "gh.log"),
    }
    return subprocess.run(
        ["bash", str(PREFLIGHT)], cwd=work, env=env, capture_output=True, text=True, timeout=60
    ).stdout


def _r(name, event, conclusion, status="completed"):
    return {"name": name, "event": event, "status": status, "conclusion": conclusion}


def _section(out):
    return out.split("== pipeline on origin/main")[1].split("==")[0]


def test_cancelled_comment_run_is_not_a_red_main(tmp_path):
    out = _run(
        tmp_path,
        [_r("Tests", "push", "success"), _r("Attestation", "issue_comment", "cancelled")],
    )
    assert "MAIN OK" in _section(out), out


def test_failed_push_run_still_reads_red(tmp_path):
    out = _run(
        tmp_path,
        [_r("Tests", "push", "failure"), _r("Attestation", "issue_comment", "success")],
    )
    assert "Tests completed failure" in _section(out), out
    assert "MAIN OK" not in _section(out)
