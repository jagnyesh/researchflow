"""#521: scripts/red_first.sh proves a test fails on the base before it passes on the change.

Runs against a throwaway git repo in tmp_path (sandbox-first: the script adds and removes a
worktree). No network, no live services; the tests inside the throwaway repo are trivial.
"""

import os
import shutil
import signal
import subprocess
import sys
import time
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
    )
    env.update(extra_env or {})
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


def test_the_script_is_executable():
    # The skill invokes it as scripts/red_first.sh.
    assert os.access(SCRIPT, os.X_OK)
    assert shutil.which("bash")


# --- #530: a red that doesn't come from the change, and a green that proves nothing ---

PYTEST_INI = "[pytest]\naddopts = --strict-markers\nmarkers =\n    slow: a slow test\n"
F_TEST = "from pkg.mod import f\n\ndef test_f():\n    assert f() == 1\n"


def _commit_all(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def test_a_conftest_fixture_added_by_the_change_is_copied_to_the_base(repo, tmp_path):
    # pkg is unchanged, so the test passes on the base code. Without the change's conftest
    # the base run goes red only because the fixture is missing.
    _write(
        repo,
        {
            "tests/conftest.py": "import pytest\n\n@pytest.fixture\ndef one():\n    return 1\n",
            "tests/test_f.py": "from pkg.mod import f\n\ndef test_f(one):\n    assert f() == one\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 1
    assert "PASSES on the base" in r.stderr


def test_a_helper_module_added_by_the_change_is_copied_to_the_base(repo, tmp_path):
    _write(
        repo,
        {
            "tests/helpers.py": "ONE = 1\n",
            "tests/test_f.py": "from helpers import ONE\nfrom pkg.mod import f\n\n"
            "def test_f():\n    assert f() == ONE\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 1
    assert "PASSES on the base" in r.stderr


def test_a_pytest_ini_marker_added_by_the_change_is_copied_to_the_base(repo, tmp_path):
    # Under --strict-markers an unregistered marker is a collection error on the base.
    (repo / "pytest.ini").write_text("[pytest]\naddopts = --strict-markers\n")
    _commit_all(repo, "ini")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _write(
        repo,
        {
            "pytest.ini": PYTEST_INI,
            "tests/test_f.py": "import pytest\nfrom pkg.mod import f\n\n@pytest.mark.slow\n"
            "def test_f():\n    assert f() == 1\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 1
    assert "PASSES on the base" in r.stderr


def test_a_run_here_where_every_test_is_skipped_is_not_green(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/newmod.py": "def g():\n    return 5\n",
            "tests/test_g.py": "import os\nimport pytest\nfrom pkg.newmod import g\n\n"
            "@pytest.mark.skipif(not os.environ.get('NEVER_SET_HERE'), reason='live')\n"
            "def test_g():\n    assert g() == 999\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_g.py")

    assert r.returncode == 1
    assert "no test passed here" in r.stderr
    assert "1 skipped" in r.stderr


def test_the_red_first_line_names_head_and_the_run_summary_here(repo, tmp_path):
    _write(
        repo,
        {
            ".gitignore": "__pycache__/\n",
            "pkg/mod.py": "def f():\n    return 2\n",
            "tests/test_f.py": "from pkg.mod import f\n\ndef test_f():\n    assert f() == 2\n",
        },
    )
    _commit_all(repo, "change")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    clean = _red_first(repo, tmp_path, "tests/test_f.py")

    line = next(ln for ln in clean.stdout.splitlines() if ln.startswith("Red-first:"))
    assert f"here {head[:12]} " in line and "uncommitted" not in line
    assert "1 passed" in line

    (repo / "pkg/mod.py").write_text("def f():\n    return 2  # edited\n")

    dirty = _red_first(repo, tmp_path, "tests/test_f.py")

    line = next(ln for ln in dirty.stdout.splitlines() if ln.startswith("Red-first:"))
    assert f"here {head[:12]}+uncommitted " in line


def test_a_base_red_that_is_a_collection_error_says_what_it_proves(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/newmod.py": "def g():\n    return 5\n",
            "tests/test_g.py": "from pkg.newmod import g\n\ndef test_g():\n    assert g() == 5\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_g.py")

    assert r.returncode == 0, r.stderr
    assert "collection error" in r.stdout
    assert "needs the change in order to import" in r.stdout


def test_an_assertion_failure_on_the_base_prints_no_collection_error_note(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/mod.py": "def f():\n    return 2\n",
            "tests/test_f.py": "from pkg.mod import f\n\ndef test_f():\n    assert f() == 2\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 0, r.stderr
    assert "collection error" not in r.stdout


def test_a_file_where_only_some_tests_are_red_says_so(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/mod.py": "def f():\n    return 2\n",
            "tests/test_f.py": "from pkg.mod import f\n\ndef test_old():\n    assert f() == 2\n\n"
            "def test_unrelated():\n    assert 1 + 1 == 2\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 0, r.stderr
    assert "1 test(s) pass on the base" in r.stdout
    assert "file::node" in r.stdout


def test_a_file_where_every_test_is_red_prints_no_partial_note(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/mod.py": "def f():\n    return 2\n",
            "tests/test_f.py": "from pkg.mod import f\n\ndef test_f():\n    assert f() == 2\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert "pass on the base" not in r.stdout


def test_base_with_no_value_is_a_usage_error(repo, tmp_path):
    _write(repo, {"tests/test_f.py": F_TEST})

    r = _red_first(repo, tmp_path, "tests/test_f.py", "--base")

    assert r.returncode == 2
    assert "usage" in r.stderr


def test_a_non_integer_timeout_is_a_usage_error(repo, tmp_path):
    _write(repo, {"tests/test_f.py": F_TEST})

    r = _red_first(repo, tmp_path, "tests/test_f.py", extra_env={"RED_FIRST_TIMEOUT": "abc"})

    assert r.returncode == 2
    assert "RED_FIRST_TIMEOUT" in r.stderr
    assert "Traceback" not in r.stderr


def _fake_python_without_pytest(tmp_path):
    fake = tmp_path / "fakepy"
    # Imports work (the import-path probe runs); only `-m pytest` fails, as in a python without it.
    fake.write_text(
        "#!/bin/sh\n"
        f'[ "$1" = "-m" ] && {{ echo "No module named pytest" >&2; exit 1; }}\n'
        f'exec "{sys.executable}" "$@"\n'
    )
    fake.chmod(0o755)
    return str(fake)


@pytest.mark.parametrize("which", ["missing", "no-pytest"])
def test_a_python_that_cannot_run_pytest_is_a_tool_error(repo, tmp_path, which):
    _write(repo, {"tests/test_f.py": F_TEST})
    py = (
        str(tmp_path / "nonexistent-python")
        if which == "missing"
        else _fake_python_without_pytest(tmp_path)
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py", extra_env={"RED_FIRST_PYTHON": py})

    assert r.returncode == 4
    assert "pytest" in r.stderr
    assert "Traceback" not in r.stderr


def test_pytest_breaking_on_the_run_here_is_a_tool_error(repo, tmp_path):
    # An ignored root conftest exists only here, so no copy step carries it to the base.
    # pytest exits 4 on the run here.
    (repo / ".gitignore").write_text("/conftest.py\n")
    _commit_all(repo, "ignore")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _write(
        repo,
        {
            "pkg/mod.py": "def f():\n    return 2\n",
            "tests/test_f.py": "from pkg.mod import f\n\ndef test_f():\n    assert f() == 2\n",
            "conftest.py": "raise RuntimeError('broken local conftest')\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 4
    assert "pytest broke" in r.stderr


def _denied_repo(repo):
    ran = repo.parent / "ran"
    _write(
        repo,
        {"tests/test_denied.py": f"open({str(ran)!r}, 'a').close()\n\ndef test_x():\n    pass\n"},
    )
    return ran


def test_a_symlink_to_a_never_run_file_is_refused(repo, tmp_path):
    ran = _denied_repo(repo)
    (repo / "tests/test_alias.py").symlink_to("test_denied.py")

    r = _red_first(repo, tmp_path, "tests/test_alias.py")

    assert r.returncode == 2
    assert "on .claude/lane-never-run.txt" in r.stderr
    assert not ran.exists()


def test_a_hard_link_to_a_never_run_file_is_refused(repo, tmp_path):
    ran = _denied_repo(repo)
    os.link(repo / "tests/test_denied.py", repo / "tests/test_hard.py")

    r = _red_first(repo, tmp_path, "tests/test_hard.py")

    assert r.returncode == 2
    assert not ran.exists()


def test_a_case_variant_of_a_never_run_file_is_refused(repo, tmp_path):
    ran = _denied_repo(repo)
    if not (repo / "tests/TEST_DENIED.PY").exists():
        pytest.skip("case-sensitive filesystem: a case variant is a different file here")

    r = _red_first(repo, tmp_path, "tests/TEST_DENIED.PY")

    assert r.returncode == 2
    assert not ran.exists()


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_timeout_kills_the_processes_the_test_started(repo, tmp_path):
    pidfile = tmp_path / "child.pid"
    _write(
        repo,
        {
            "pkg/mod.py": "def f():\n    return 2\n",
            "tests/test_f.py": "import subprocess, time\n\ndef test_f():\n"
            "    p = subprocess.Popen(['sleep', '600'])\n"
            f"    open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
            "    time.sleep(120)\n",
        },
    )
    try:
        r = _red_first(repo, tmp_path, "tests/test_f.py", extra_env={"RED_FIRST_TIMEOUT": "3"})
        time.sleep(0.5)
        leaked = pidfile.exists() and _alive(int(pidfile.read_text()))
    finally:
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass

    assert r.returncode == 4
    assert "timed out" in r.stderr
    assert not leaked


def test_the_import_path_probe_takes_several_packages(repo, tmp_path):
    # pkg is fine; newpkg exists only in the change and leaks through PYTHONPATH.
    _write(
        repo,
        {
            "newpkg/__init__.py": "VALUE = 7\n",
            "tests/test_new.py": "from newpkg import VALUE\n\ndef test_v():\n    assert VALUE == 7\n",
        },
    )

    r = _red_first(
        repo,
        tmp_path,
        "tests/test_new.py",
        package="pkg, newpkg",
        extra_env={"PYTHONPATH": str(repo)},
    )

    assert r.returncode == 3
    assert "import-path check failed" in r.stderr and "newpkg" in r.stderr


def test_a_root_conftest_added_by_the_change_is_copied_to_the_base(repo, tmp_path):
    _write(
        repo,
        {
            "conftest.py": "import pytest\n\n@pytest.fixture\ndef one():\n    return 1\n",
            "tests/test_f.py": "from pkg.mod import f\n\ndef test_f(one):\n    assert f() == one\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 1
    assert "PASSES on the base" in r.stderr


@pytest.mark.parametrize(
    "name,before,after",
    [
        (
            "pyproject.toml",
            '[tool.pytest.ini_options]\naddopts = "--strict-markers"\n',
            '[tool.pytest.ini_options]\naddopts = "--strict-markers"\nmarkers = ["slow: slow"]\n',
        ),
        (
            "setup.cfg",
            "[tool:pytest]\naddopts = --strict-markers\n",
            "[tool:pytest]\naddopts = --strict-markers\nmarkers =\n    slow: slow\n",
        ),
        (
            "tox.ini",
            "[pytest]\naddopts = --strict-markers\n",
            "[pytest]\naddopts = --strict-markers\nmarkers =\n    slow: slow\n",
        ),
    ],
)
def test_every_pytest_config_file_the_change_touches_is_copied_to_the_base(
    repo, tmp_path, name, before, after
):
    (repo / name).write_text(before)
    _commit_all(repo, "config")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _write(
        repo,
        {
            name: after,
            "tests/test_f.py": "import pytest\nfrom pkg.mod import f\n\n@pytest.mark.slow\n"
            "def test_f():\n    assert f() == 1\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 1
    assert "PASSES on the base" in r.stderr


def test_a_project_that_adds_dash_q_still_gets_its_counts(repo, tmp_path):
    # With -q in addopts the script's own -q makes -qq, and pytest prints no totals line.
    (repo / "pytest.ini").write_text("[pytest]\naddopts = -q\n")
    _commit_all(repo, "ini")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _write(
        repo,
        {
            "pkg/mod.py": "def f():\n    return 2\n",
            "tests/test_f.py": "import pytest\nfrom pkg.mod import f\n\n"
            "def test_f():\n    assert f() == 2\n\n"
            "@pytest.mark.skip(reason='x')\ndef test_skipped():\n    pass\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 0, r.stderr
    line = next(ln for ln in r.stdout.splitlines() if ln.startswith("Red-first:"))
    assert "1 passed, 1 skipped" in line


def test_a_conftest_that_cannot_import_on_the_base_says_so(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/newmod.py": "VALUE = 1\n",
            "tests/conftest.py": "from pkg.newmod import VALUE\n",
            "tests/test_f.py": "def test_f():\n    assert True\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 4
    assert "conftest.py" in r.stderr and "can't load on the base" in r.stderr


def test_a_sigterm_kills_the_processes_the_test_started(repo, tmp_path):
    pidfile = tmp_path / "child.pid"
    _write(
        repo,
        {
            "pkg/mod.py": "def f():\n    return 2\n",
            "tests/test_f.py": "import subprocess, time\n\ndef test_f():\n"
            "    p = subprocess.Popen(['sleep', '600'])\n"
            f"    open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
            "    time.sleep(120)\n",
        },
    )
    scratch_tmp = tmp_path / "scratch-tmp"
    scratch_tmp.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(TMPDIR=str(scratch_tmp), RED_FIRST_PYTHON=sys.executable, RED_FIRST_PACKAGE="pkg")
    proc = subprocess.Popen(
        ["bash", str(SCRIPT), "tests/test_f.py"],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child = None
    try:
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text():
                child = int(pidfile.read_text())
                break
            time.sleep(0.1)
        assert child is not None, "the test never started its child"
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=30)
        for _ in range(50):
            if not _alive(child):
                break
            time.sleep(0.1)
        leaked = _alive(child)
    finally:
        if proc.poll() is None:
            proc.kill()
        if child is not None:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass

    assert proc.returncode == 128 + signal.SIGTERM
    assert not leaked
    assert list(scratch_tmp.iterdir()) == []


def test_a_run_here_whose_only_green_test_is_an_xpass_is_not_green(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/newmod.py": "def g():\n    return 2\n",
            "tests/test_g.py": "import pytest\nfrom pkg.newmod import g\n\n"
            "@pytest.mark.xfail\ndef test_g():\n    assert g() == 2\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_g.py")

    assert r.returncode == 1
    assert "no test passed here" in r.stderr


def test_the_base_output_block_carries_no_platform_or_rootdir_line(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/mod.py": "def f():\n    return 2\n",
            "tests/test_f.py": "from pkg.mod import f\n\ndef test_f():\n    assert f() == 2\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_f.py")

    assert r.returncode == 0, r.stderr
    assert "rootdir" not in r.stdout and "platform" not in r.stdout


def test_text_that_says_passed_after_the_totals_line_does_not_make_an_all_skipped_run_green(
    repo, tmp_path
):
    _write(
        repo,
        {
            "pkg/newmod.py": "import atexit\natexit.register(print, '9 passed in 0.01s')\n"
            "def g():\n    return 2\n",
            "tests/test_g.py": "import pytest\nfrom pkg.newmod import g\n\n"
            "@pytest.mark.skip(reason='4 passed on ci')\ndef test_g():\n    assert g() == 2\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_g.py")

    assert r.returncode == 1
    assert "no test passed here" in r.stderr


def test_the_base_output_block_has_no_local_paths(repo, tmp_path):
    _write(
        repo,
        {
            "pkg/newmod.py": "def g():\n    return 5\n",
            "tests/test_g.py": "from pkg.newmod import g\n\ndef test_g():\n    assert g() == 5\n",
        },
    )

    r = _red_first(repo, tmp_path, "tests/test_g.py")

    assert r.returncode == 0, r.stderr
    assert str(tmp_path.resolve()) not in r.stdout and str(tmp_path) not in r.stdout
    assert "<base>/tests/test_g.py" in r.stdout
