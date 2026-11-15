"""Exit code and log lines of scripts/refresh_materialized_views.py (#437).

The result comes from the real MaterializedViewService.list_views and
refresh_all_views. Only the database edge is faked: the HAPI client fails the
REFRESH statement for one view, and nothing touches the live :5433 views.
"""

import importlib.util
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.materialized_view_service import MaterializedViewService

SCRIPT = Path(__file__).parent.parent / "scripts" / "refresh_materialized_views.py"
VIEWS = ["view_a", "view_b", "view_c"]


class FakeHapiClient:
    def __init__(self, failing_view=None):
        self.failing_view = failing_view
        self.close = AsyncMock()

    async def execute_query(self, sql):
        if "pg_matviews" in sql:
            return [{"view_name": v, "size": "1 kB", "size_bytes": 1024} for v in VIEWS]
        if sql.startswith("REFRESH") and self.failing_view and self.failing_view in sql:
            raise RuntimeError("lock timeout")
        if "COUNT(*)" in sql:
            return [{"count": 5}]
        return [{"size_bytes": 1024}]


def _load_script():
    spec = importlib.util.spec_from_file_location("refresh_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _service(failing_view):
    session = MagicMock()
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=rows)
    session.close = AsyncMock()
    service = MaterializedViewService(FakeHapiClient(failing_view), session)
    service._update_metadata = AsyncMock()  # metadata table is not under test
    return service


async def _run(monkeypatch, failing_view):
    script = _load_script()
    service = _service(failing_view)
    monkeypatch.setattr(script.MaterializedViewService, "create", AsyncMock(return_value=service))
    return await script.refresh_all_views()


@pytest.mark.asyncio
async def test_failed_view_exits_nonzero_and_logs_counts(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    code = await _run(monkeypatch, failing_view="view_b")

    assert code == 1
    assert "Views refreshed: 2" in caplog.text
    assert "Views failed: 1" in caplog.text
    # Emitted by the script's own error loop; the service's log line has no "  - " prefix.
    assert "  - view_b: " in caplog.text


@pytest.mark.asyncio
async def test_all_views_ok_exits_zero(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    code = await _run(monkeypatch, failing_view=None)

    assert code == 0
    assert "Views refreshed: 3" in caplog.text
    assert "Views failed: 0" in caplog.text
