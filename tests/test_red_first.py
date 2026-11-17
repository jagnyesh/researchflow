"""#521: scripts/red_first.sh proves a test fails on the base before it passes on the change.

Runs against a throwaway git repo in tmp_path (sandbox-first: the script adds and removes a
worktree). No network, no live services; the tests inside the throwaway repo are trivial.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/red_first.sh"

# Split so this file doesn't itself carry the marker text that the never-run list refuses.
MARKER = "requires_" + "services"

BASE_FILES = {
    "pkg/__init__.py": "",
    "pkg/mod.py": "def f():\n    return 1\n",
    ".claude/lane-never-run.txt": f"file: tests/test_denied.py\nmarker: {MARKER}\n",
}


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, BASE_FILES)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def _red_first(repo, tmp_path, *targets, package="pkg", extra_env=None):
    scratch_tmp = tmp_path / "scratch-tmp"
    scratch_tmp.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(
        TMPDIR=str(scratch_tmp),
        RED_FIRST_PYTHON=sys.executable,
        RED_FIRST_PACKAGE=package,
        **(extra_env or {}),
    )
    r = subprocess.run(
        ["bash", str(SCRIPT), *targets], cwd=repo, env=env, capture_output=True, text=True
    )
    # Every exit path removes the temporary worktree and its directory.
    assert list(scratch_tmp.iterdir()) == []
    wts = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert wts.count("worktree ") == 1
    return r


def test_a_test_red_on_the_base_and_green_here_passes_and_prints_the_base_output(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/mod.py": "def f():\n    return 2\n",
            "tests/test_f.py": "from pkg.mod import f\n\ndef test_f():\n    assert f() == 2\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 0, r.stderr
    assert "Red-first: tests/test_f.py" in r.stdout
    assert "assert 1 == 2" in r.stdout  # the base run's failure, for the PR's evidence


def test_a_node_id_is_accepted(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/mod.py": "def f():\n    return 2\n",
            "tests/test_f.py": "from pkg.mod import f\n\ndef test_f():\n    assert f() == 2\n",
        },
    )

    assert _red_first(repo, tmp_path, "tests/test_f.py::test_f").returncode == 0


def test_a_collection_error_on_the_base_counts_as_red(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/newmod.py": "def g():\n    return 5\n",
            "tests/test_g.py": "from pkg.newmod import g\n\ndef test_g():\n    assert g() == 5\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_g.py")

    assert r.returncode == 0, r.stderr
    assert "ModuleNotFoundError" in r.stdout


def test_a_test_that_passes_on_the_base_fails_and_names_the_test(repo, tmp_path):
    _write(
        repo,
        {"tests/test_f.py": "from pkg.mod import f\n\ndef test_f():\n    assert f() == 1\n"},
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 1
    assert "tests/test_f.py" in r.stderr and "PASSES on the base" in r.stderr


def test_a_file_that_collects_no_tests_fails(repo, tmp_path):
    _write(repo, {"tests/test_empty.py": "X = 1\n"})

    r = _red_first(repo, tmp_path, "tests/test_empty.py")

    assert r.returncode == 1
    assert "collected no tests" in r.stderr


def test_a_test_that_still_fails_here_fails(repo, tmp_path):
    _write(
        repo,
        {"tests/test_f.py": "from pkg.mod import f\n\ndef test_f():\n    assert f() == 3\n"},
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 1
    assert "fails here too" in r.stderr


def test_a_file_on_the_never_run_list_is_refused_without_running(repo, tmp_path):
    ran = tmp_path / "ran"
    _write(
        repo,
        {"tests/test_denied.py": f"open({str(ran)!r}, 'w').close()\n\ndef test_x():\n    pass\n"},
    )

    r = _red_first(repo, tmp_path, "tests/test_denied.py")

    assert r.returncode == 2
    assert "refusing tests/test_denied.py" in r.stderr
    assert not ran.exists()


def test_a_file_carrying_a_never_run_marker_is_refused(repo, tmp_path):
    _write(
        repo,
        {
            "tests/test_live.py": f"import pytest\n\npytestmark = pytest.mark.{MARKER}\n\ndef test_x():\n    pass\n"
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_live.py")

    assert r.returncode == 2
    assert f"marked {MARKER}" in r.stderr


def test_a_missing_never_run_list_refuses_everything(repo, tmp_path):
    (repo / ".claude/lane-never-run.txt").unlink()
    _write(repo, {"tests/test_f.py": "def test_f():\n    assert False\n"})

    assert _red_first(repo, tmp_path, "tests/test_f.py").returncode == 2


def test_a_package_importable_from_this_checkout_fails_the_import_path_check(repo, tmp_path):
    # newpkg exists only in the change. With PYTHONPATH pointing at this checkout, the
    # base run would import the change's code and the test would go green there.
    _write(
        repo,
        {
            "newpkg/__init__.py": "VALUE = 7\n",
            "tests/test_new.py": "from newpkg import VALUE\n\ndef test_v():\n    assert VALUE == 7\n",
        },
    )

    r = _red_first(
        repo, tmp_path, "tests/test_new.py", package="newpkg", extra_env={"PYTHONPATH": str(repo)}
    )

    assert r.returncode == 3
    assert "import-path check failed" in r.stderr


def test_the_same_change_without_a_stray_path_is_red_first(repo, tmp_path):
    _write(
        repo,
        {
            "newpkg/__init__.py": "VALUE = 7\n",
            "tests/test_new.py": "from newpkg import VALUE\n\ndef test_v():\n    assert VALUE == 7\n",
        },
    )

    assert _red_first(repo, tmp_path, "tests/test_new.py", package="newpkg").returncode == 0


def test_the_script_is_executable_from_a_copy_in_another_repo():
    # Guards the shebang and exec line: the skill invokes it as scripts/red_first.sh.
    assert os.access(SCRIPT, os.X_OK)
    assert shutil.which("bash")
