"""`create_materialized_views.py` must fail loudly when a view fails (#182).

It used to catch each view's error, print it, and exit 0 — so
`POST /analytics/materialized-views/create-all` reported success for a
partial build. Runs the script's real `main()` against Postgres in a
throwaway schema with templates that need no HAPI tables.
"""

import asyncio
import importlib.util
import os
from pathlib import Path

import asyncpg
import pytest

pytestmark = pytest.mark.requires_services

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_materialized_views.py"
SCHEMA = "rf_test_182"
MISSING_TABLE = "rf_no_such_table_182"


def _load_script():
    spec = importlib.util.spec_from_file_location("create_mv_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(monkeypatch):
    module = _load_script()
    monkeypatch.setattr(module, "SCHEMA_NAME", SCHEMA)
    monkeypatch.setattr(module, "SKIP_VALIDATION", True)
    yield module

    async def _drop():
        conn = await asyncpg.connect(module.HAPI_DB_URL)
        try:
            await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        finally:
            await conn.close()

    asyncio.run(_drop())


def test_exits_nonzero_when_any_view_fails(script, monkeypatch, capsys):
    monkeypatch.setattr(
        script,
        "VIEW_TEMPLATES",
        {"good_view": "SELECT 1 AS x", "bad_view": f"SELECT * FROM {MISSING_TABLE}"},
    )

    with pytest.raises(SystemExit) as exc:
        asyncio.run(script.main())

    assert exc.value.code not in (0, None)


def test_failure_output_names_the_view_not_the_error(script, monkeypatch, capsys):
    """Driver messages can carry row values (#175); print the view and the
    exception type only."""
    monkeypatch.setattr(script, "VIEW_TEMPLATES", {"bad_view": f"SELECT * FROM {MISSING_TABLE}"})

    with pytest.raises(SystemExit):
        asyncio.run(script.main())

    out = capsys.readouterr().out
    assert "bad_view" in out
    assert "UndefinedTableError" in out
    assert MISSING_TABLE not in out


def test_full_build_exits_cleanly_with_a_parseable_result(script, monkeypatch, capsys):
    """The RESULT line is the script↔API contract; pin it on a real run."""
    from app.api.materialized_views import _SCRIPT_RESULT

    monkeypatch.setattr(script, "VIEW_TEMPLATES", {"good_view": "SELECT 1 AS x"})

    asyncio.run(script.main())  # no SystemExit

    match = _SCRIPT_RESULT.search(capsys.readouterr().out)
    assert match and (match["created"], match["total"]) == ("1", "1")
