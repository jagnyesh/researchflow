"""
#367 — the exploratory notebook's startup output carries no part of the API key.

The page runs through ``streamlit.testing`` the way ``streamlit run`` executes it,
so the startup check prints to this process's stdout, where capfd reads it.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

NOTEBOOK = str(Path(__file__).resolve().parents[1] / "app" / "web_ui" / "research_notebook.py")

# Every Anthropic key opens with this fixed prefix; only what follows is secret.
PUBLIC_PREFIX = "sk-ant-api03-"
SECRET_TAIL = "TESTONLYnotarealkeyQ7"
FAKE_KEY = PUBLIC_PREFIX + SECRET_TAIL  # pragma: allowlist secret


def _startup_output(monkeypatch, capfd) -> str:
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    capfd.readouterr()
    at = AppTest.from_file(NOTEBOOK, default_timeout=60).run()
    assert not at.exception
    captured = capfd.readouterr()
    return captured.out + captured.err


def test_startup_output_carries_no_slice_of_the_key(monkeypatch, capfd):
    out = _startup_output(monkeypatch, capfd)

    # A head slice leaks as soon as it passes the prefix; any other slice shows
    # up as a run of tail characters.
    probes = {PUBLIC_PREFIX + SECRET_TAIL[0]}
    probes |= {SECRET_TAIL[i : i + 4] for i in range(len(SECRET_TAIL) - 3)}
    leaked = sorted(p for p in probes if p in out)
    assert not leaked, f"startup output carries part of the key: {leaked}"


def test_startup_output_reports_the_key_is_loaded_and_from_where(monkeypatch, capfd):
    out = _startup_output(monkeypatch, capfd)

    assert "ANTHROPIC_API_KEY" in out
    assert str(Path(NOTEBOOK).parents[2] / ".env") in out
