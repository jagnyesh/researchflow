"""`create_materialized_views.py` must accept both HAPI_DB_URL schemes (#390).

asyncpg rejects `postgresql+asyncpg://`, the form the host .env and compose
use. No database is touched: connections go to a closed port.
"""

import asyncio
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_materialized_views.py"
CLOSED = "localhost:1/hapi"


def _load_script():
    spec = importlib.util.spec_from_file_location("create_mv_script_dsn", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("scheme", ["postgresql", "postgresql+asyncpg"])
def test_dsn_is_accepted_by_asyncpg(scheme, monkeypatch):
    """Both schemes get past DSN parsing: failure is a refused connection, not ValueError."""
    script = _load_script()
    monkeypatch.setattr(script, "HAPI_DB_URL", f"{scheme}://u:secret@{CLOSED}")
    monkeypatch.setattr(script, "SKIP_VALIDATION", True)

    with pytest.raises(OSError):
        asyncio.run(script.main())


def test_asyncpg_dsn_strips_only_the_dialect():
    script = _load_script()
    assert script._asyncpg_dsn("postgresql+asyncpg://u:p@h:1/d") == "postgresql://u:p@h:1/d"
    assert script._asyncpg_dsn("postgresql://u:p@h:1/d") == "postgresql://u:p@h:1/d"


@pytest.mark.parametrize("scheme", ["postgresql", "postgresql+asyncpg"])
def test_redacted_has_no_credentials(scheme):
    script = _load_script()
    out = script._redacted(f"{scheme}://user:secret@{CLOSED}")
    assert out == CLOSED
    assert "secret" not in out and "user" not in out
