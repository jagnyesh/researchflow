"""Phase 3b — encryption-at-rest: key callable + lifespan startup gate."""

import os

import pytest
from cryptography.fernet import Fernet


def test_get_encryption_key_returns_env_var_value(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY_PRIMARY", "test-fernet-key-bytes")
    from app.security.encryption_keys import get_encryption_key

    assert get_encryption_key() == b"test-fernet-key-bytes"


def test_assert_key_is_noop_when_environment_is_not_production(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY_PRIMARY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    from app.security.encryption_keys import assert_encryption_key_present_if_production

    assert_encryption_key_present_if_production()  # no exception


def test_assert_key_raises_in_production_when_key_missing(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY_PRIMARY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    from app.security.encryption_keys import assert_encryption_key_present_if_production

    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY_PRIMARY"):
        assert_encryption_key_present_if_production()


def test_assert_key_raises_in_production_when_key_is_malformed(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY_PRIMARY", "not-a-valid-fernet-key")
    monkeypatch.setenv("ENVIRONMENT", "production")
    from app.security.encryption_keys import assert_encryption_key_present_if_production

    with pytest.raises(RuntimeError, match="not a valid Fernet key"):
        assert_encryption_key_present_if_production()


def test_assert_key_passes_in_production_with_valid_fernet_key(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY_PRIMARY", Fernet.generate_key().decode())
    monkeypatch.setenv("ENVIRONMENT", "production")
    from app.security.encryption_keys import assert_encryption_key_present_if_production

    assert_encryption_key_present_if_production()  # no exception


def test_lifespan_invokes_encryption_key_gate_on_startup():
    """The startup gate runs on every app boot. Wiring is the regression target —
    if `assert_encryption_key_present_if_production` is removed from the lifespan,
    a misconfigured production deploy would silently start.
    """
    import inspect

    import app.main as main_mod

    src = inspect.getsource(main_mod.lifespan)
    assert "assert_encryption_key_present_if_production" in src
    # Confirm it's also imported at module level (not just referenced as a string).
    assert hasattr(main_mod, "assert_encryption_key_present_if_production")


def test_streamlit_dashboards_invoke_encryption_key_gate_on_startup():
    """CSO Phase 3b Finding 2 fix: each streamlit dashboard process starts
    independently of the FastAPI lifespan. Without an explicit gate call, a
    typo'd `ENCRYPTION_KEY_PRIMARY` surfaces as `cryptography.fernet.InvalidToken`
    on the first PHI access — burying the misconfiguration in a confusing stack
    trace instead of the clean RuntimeError the gate is designed to produce.

    Read source as text rather than importing — streamlit modules trigger
    page-config side effects on import that don't belong in test collection.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    entry_points = [
        "app/web_ui/admin_dashboard.py",
        "app/web_ui/researcher_portal.py",
        "app/web_ui/research_notebook.py",
    ]

    for relpath in entry_points:
        src = (repo_root / relpath).read_text()
        assert (
            "assert_encryption_key_present_if_production()" in src
        ), f"{relpath} must CALL the encryption key gate at startup (not just reference it)"
        assert (
            "from app.security.encryption_keys import" in src
            or "from .security.encryption_keys import" in src
            or "from ..security.encryption_keys import" in src
        ), f"{relpath} must import the gate explicitly"
