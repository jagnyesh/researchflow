"""
#367 — the exploratory notebook's startup output carries no part of the API key.

The page runs through ``streamlit.testing`` the way ``streamlit run`` executes it,
so the startup check prints to this process's stdout, where capfd reads it. Log
records are read from caplog. Under ``streamlit run``, an unhandled WARNING
reaches stderr through logging's last-resort handler, but under pytest the
logging plugin takes the record before capfd can see it.
"""

import logging
import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

NOTEBOOK = str(Path(__file__).resolve().parents[1] / "app" / "web_ui" / "research_notebook.py")

# Every Anthropic key opens with this fixed prefix; only what follows is secret.
# The tail is not made of words, so ordinary output can't match a probe by chance.
PUBLIC_PREFIX = "sk-ant-api03-"
SECRET_TAIL = "Zq7xK2vP9mW4QjR8"  # pragma: allowlist secret
FAKE_KEY = PUBLIC_PREFIX + SECRET_TAIL  # pragma: allowlist secret


def _startup_output(monkeypatch, capfd, caplog) -> str:
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    caplog.set_level(logging.DEBUG)
    capfd.readouterr()
    at = AppTest.from_file(NOTEBOOK, default_timeout=60).run()
    assert not at.exception
    captured = capfd.readouterr()
    return captured.out + captured.err + caplog.text


def test_startup_output_carries_no_slice_of_the_key(monkeypatch, capfd, caplog):
    out = _startup_output(monkeypatch, capfd, caplog)

    # A head slice of any key, not only the one this test set, runs past the prefix.
    assert not re.search(re.escape(PUBLIC_PREFIX) + r"\S", out), "startup output carries a key head"
    # Any other slice of the test key shows up as a run of its tail.
    windows = {SECRET_TAIL[i : i + 4] for i in range(len(SECRET_TAIL) - 3)}
    leaked = sorted(w for w in windows if w in out)
    assert not leaked, f"startup output carries part of the key: {leaked}"


def test_startup_output_reports_the_key_is_set_and_which_env_was_checked(
    monkeypatch, capfd, caplog
):
    out = _startup_output(monkeypatch, capfd, caplog)

    assert "ANTHROPIC_API_KEY is set" in out
    assert "ANTHROPIC_API_KEY not found" not in out
    assert str(Path(NOTEBOOK).parents[2] / ".env") in out
