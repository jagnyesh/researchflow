"""#438: a view whose last refresh failed must not read as healthy."""

import pytest

from app.api import materialized_views as api
from app.services.materialized_view_service import view_health


def _view(name, status="active", is_stale=False):
    return {"view_name": name, "status": status, "is_stale": is_stale}


@pytest.mark.parametrize(
    "view,expected",
    [
        (_view("a"), "healthy"),
        (_view("a", is_stale=True), "stale"),
        (_view("a", status="failed"), "failed"),
        # failed outranks stale: the refresh error is the actionable one
        (_view("a", status="failed", is_stale=True), "failed"),
        # a view that never got metadata has no refresh evidence either way
        (_view("a", status="unknown"), "healthy"),
        # a refresh in flight is not a failure; the old data is still served
        (_view("a", status="refreshing"), "healthy"),
    ],
)
def test_view_health_rule(view, expected):
    assert view_health(view) == expected


class _FakeService:
    def __init__(self, views):
        self._views = views

    async def list_views(self):
        return self._views

    async def close(self):
        pass


async def _health(monkeypatch, views):
    async def fake_get_service():
        return _FakeService(views)

    monkeypatch.setattr(api, "get_service", fake_get_service)
    return await api.health_check()


@pytest.mark.asyncio
async def test_health_degraded_and_names_failed_view(monkeypatch):
    out = await _health(monkeypatch, [_view("ok_view"), _view("bad_view", status="failed")])
    assert out["status"] == "degraded"
    assert out["failed_views"] == ["bad_view"]
    assert out["healthy_views"] == 1


@pytest.mark.asyncio
async def test_health_healthy_when_all_active(monkeypatch):
    out = await _health(monkeypatch, [_view("a"), _view("b")])
    assert out["status"] == "healthy"
    assert out["failed_views"] == []


@pytest.mark.asyncio
async def test_health_still_degraded_on_stale(monkeypatch):
    out = await _health(monkeypatch, [_view("a", is_stale=True)])
    assert out["status"] == "degraded"
    assert out["stale_views"] == 1
