"""#274: /health covers the stores the app reads, and compose keeps them up.

Real connections; unreachable stores are real closed ports, not stubs.
"""

from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.health import router as health_router

COMPOSE = Path(__file__).resolve().parent.parent / "config/docker-compose.yml"
CLOSED = "127.0.0.1:1"


async def _health(monkeypatch, **env):
    from app.database import init_db
    from app.security import audit_middleware as am

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(am, "_audit_redis", None)
    await init_db()
    app = FastAPI()
    app.include_router(health_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/health")
    return resp.json(), resp.text


@pytest.mark.asyncio
async def test_unreachable_stores_are_reported_without_leaking_where_they_are(monkeypatch):
    body, text = await _health(
        monkeypatch,
        HAPI_DB_URL=f"postgresql://hapi:hapi@{CLOSED}/hapi",  # pragma: allowlist secret
        REDIS_URL=f"redis://{CLOSED}/0",
        REDIS_AUDIT_URL=f"redis://{CLOSED}/0",
    )

    components = body["components"]
    assert components["hapi_database"]["status"] == "unhealthy"
    assert components["audit_redis"]["status"] == "unhealthy"
    assert components["speed_layer_redis"]["status"] == "unhealthy"
    assert body["status"] == "unhealthy"
    assert CLOSED not in text and "hapi:hapi" not in text  # pragma: allowlist secret


@pytest.mark.requires_services
@pytest.mark.asyncio
async def test_reachable_hapi_database_is_healthy(monkeypatch):
    body, _ = await _health(monkeypatch)

    assert body["components"]["hapi_database"] == {"status": "healthy"}


def test_every_compose_service_restarts_and_waits_only_on_real_healthchecks():
    services = yaml.safe_load(COMPOSE.read_text())["services"]

    assert {name for name, s in services.items() if "restart" not in s} == set()
    for name, svc in services.items():
        for dep, cond in (svc.get("depends_on") or {}).items():
            if cond.get("condition") == "service_healthy":
                assert "healthcheck" in services[dep], f"{name} waits on {dep}, which has none"
