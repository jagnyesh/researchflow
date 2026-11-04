"""#171: every tool a CI workflow pip-installs is pinned.

A floating scanner release can turn CI red with no code change (#156/#158
class). Allowed: `-r <lock>`, `-c <lock> <pkg>` (constrained by a lock), the
pip self-upgrade, and exact `==` pins.
"""

import re
import shlex
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github/workflows"


def _unpinned(line: str) -> list:
    args = shlex.split(line.split("pip install", 1)[1], comments=True)
    if "-r" in args or "-c" in args or args[:2] == ["--upgrade", "pip"]:
        return []
    return [a for a in args if not a.startswith("-") and not re.search(r"==\S+$", a)]


def test_no_workflow_pip_installs_an_unpinned_tool():
    offenders = [
        f"{wf.name}:{n}: {line.strip()}"
        for wf in sorted(WORKFLOWS.glob("*.yml"))
        for n, line in enumerate(wf.read_text().splitlines(), 1)
        if "pip install" in line and _unpinned(line)
    ]

    assert offenders == [], "unpinned CI installs:\n" + "\n".join(offenders)


def test_bandit_pins_match_the_dev_lock():
    lock = (WORKFLOWS.parent.parent / "config/requirements-dev.lock").read_text()
    locked = re.search(r"^bandit==(\S+)", lock, re.M).group(1)
    pins = {
        m.group(1)
        for wf in WORKFLOWS.glob("*.yml")
        for m in re.finditer(r"bandit(?:\[toml\])?==([0-9][^\s'\"]*)", wf.read_text())
    }

    assert pins == {locked}
