"""Streamlit portals bind to loopback, with XSRF protection on (#208).

Streamlit with no server.address listens on every interface, so the three
unauthenticated dashboards (#39) were reachable from the LAN under every
documented launch command. The repo config is the one place all of those
commands share. Resolved through Streamlit's own config loader, so a key in
the wrong section fails here instead of being silently ignored.
"""

from pathlib import Path

import pytest
from streamlit import config

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_streamlit_config(monkeypatch):
    # Streamlit reads .streamlit/config.toml relative to the launch directory.
    monkeypatch.chdir(REPO_ROOT)
    config.get_config_options(force_reparse=True)
    yield config
    config.get_config_options(force_reparse=True)


def test_portals_bind_to_loopback(repo_streamlit_config):
    assert repo_streamlit_config.get_option("server.address") == "127.0.0.1"


def test_xsrf_protection_enabled(repo_streamlit_config):
    assert repo_streamlit_config.get_option("server.enableXsrfProtection") is True
    # enableCORS=false is overridden whenever XSRF is on; keep the file honest.
    assert repo_streamlit_config.get_option("server.enableCORS") is True
