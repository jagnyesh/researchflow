"""#171: every tool a CI workflow pip-installs is pinned.

A floating scanner release can turn CI red with no code change (#156/#158
class). Allowed: `-r <lock>`, `-c <lock> <pkg>` (constrained by a lock), the
pip self-upgrade, and exact `==` pins.
"""

import re
import shlex
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github/workflows"


def _unpinned_in_block(text: str) -> list:
    """Unpinned packages across every pip install in a shell block.

    Joins `\\` continuations, matches pip and pip3 (also via python -m), and
    exempts only the argument that follows -r/-c, not the whole command. A
    package installed under `-c <lock>` is pinned when that lock lists it.
    """
    text = re.sub(r"\\\n\s*", " ", text)
    found = []
    for m in re.finditer(r"\bpip3?\s+install\b(.*)", text):
        args = shlex.split(m.group(1), comments=True)
        constrained = set()
        for flag, path in zip(args, args[1:]):
            if flag in ("-c", "--constraint"):
                lock = (WORKFLOWS.parent.parent / path).read_text().lower()
                constrained |= set(re.findall(r"^([a-z0-9_.-]+)==", lock, re.M))
        skip_next = False
        for i, a in enumerate(args):
            if skip_next:
                skip_next = False
            elif a in ("-r", "-c", "--requirement", "--constraint"):
                skip_next = True
            elif re.split(r"[\[=<>~!]", a)[0].lower() in constrained:
                continue
            elif a.startswith("-"):
                continue
            elif a == "pip" and i > 0 and args[i - 1] in ("--upgrade", "-U"):
                continue
            elif not re.search(r"==[0-9][^*]*$", a):
                found.append(a)
    return found


def _workflow_files():
    return sorted(p for p in WORKFLOWS.iterdir() if p.suffix in (".yml", ".yaml"))


def test_no_workflow_pip_installs_an_unpinned_tool():
    offenders = {
        wf.name: _unpinned_in_block(wf.read_text())
        for wf in _workflow_files()
        if _unpinned_in_block(wf.read_text())
    }

    assert offenders == {}, f"unpinned CI installs: {offenders}"


def test_bandit_pins_match_the_dev_lock():
    lock = (WORKFLOWS.parent.parent / "config/requirements-dev.lock").read_text()
    locked = re.search(r"^bandit==(\S+)", lock, re.M).group(1)
    pins = {
        m.group(1)
        for wf in _workflow_files()
        for m in re.finditer(r"bandit(?:\[toml\])?==([0-9][^\s'\"]*)", wf.read_text())
    }

    assert pins == {locked}


@pytest.mark.parametrize(
    "run_block,unpinned",
    [
        ("pip3 install safety", ["safety"]),
        ("pip install -r config/requirements.lock foo", ["foo"]),
        ("pip install -c config/requirements-dev.lock pre-commit", []),
        ("pip install -c config/requirements-dev.lock not-in-the-lock", ["not-in-the-lock"]),
        ("pip install foo==1.*", ["foo==1.*"]),
        ("pip install foo==1.2 \\\n  bar", ["bar"]),
        ("python -m pip install --upgrade pip", []),
        ("pip install 'bandit[toml]==1.9.4'  # matches the lock", []),
    ],
)
def test_the_guard_catches_realistic_install_forms(run_block, unpinned):
    assert _unpinned_in_block(run_block) == unpinned
