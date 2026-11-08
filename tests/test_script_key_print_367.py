"""
#367 — no tracked shell script expands a slice of a secret-named variable.

A slice such as ``${LANGCHAIN_API_KEY:0:20}`` prints secret characters past a
key's public prefix. Default expansions such as ``${API_KEY:-}`` are not slices
and stay allowed.
"""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Offset forms bash accepts: ${V:3}, ${V: -4}, ${V:(-4)}. ${V:-x} is a default, not a slice.
SECRET_SLICE = re.compile(
    r"\$\{[A-Za-z0-9_]*(KEY|TOKEN|SECRET|PASS|CREDENTIAL)[A-Za-z0-9_]*:(\s*\(?\s*-?[0-9]|\s+-)",
    re.IGNORECASE,
)


def _shell_scripts() -> list:
    out = subprocess.run(
        ["git", "ls-files", "*.sh", "*.bash"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    assert out, "git ls-files found no shell scripts"
    return [REPO / p for p in out]


def test_the_pattern_catches_slices_and_skips_defaults():
    for leak in (
        '"${LANGCHAIN_API_KEY:0:20}"',
        "${ANTHROPIC_API_KEY: -4}",
        "${github_token:(-4)}",
        "${DB_PASSWORD:3}",
    ):
        assert SECRET_SLICE.search(leak), leak
    for safe in ("${ANTHROPIC_API_KEY:-}", "${API_KEY:+set}", "${#API_KEY}", "${PORT:0:2}"):
        assert not SECRET_SLICE.search(safe), safe


def test_no_shell_script_prints_a_slice_of_a_secret_variable():
    hits = [
        f"{path.relative_to(REPO)}:{n}: {line.strip()}"
        for path in _shell_scripts()
        for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1)
        if SECRET_SLICE.search(line)
    ]
    assert not hits, "shell scripts expand a slice of a secret variable:\n" + "\n".join(hits)
