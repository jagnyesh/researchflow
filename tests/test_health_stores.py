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


@pytest.mark.asyncio
async def test_a_hung_audit_redis_cannot_stall_health(monkeypatch):
    # A server that accepts the connection and never answers: the live audit
    # client has no socket timeout of its own, so the probe must bound it.
    import asyncio
    import time

    import redis.asyncio as redis_async

    from app.api import health as health_module
    from app.security import audit_middleware as am

    async def never_reply(reader, writer):
        await asyncio.sleep(3600)

    server = await asyncio.start_server(never_reply, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    hung = redis_async.from_url(f"redis://127.0.0.1:{port}/0")
    monkeypatch.setattr(am, "_audit_redis", hung)
    monkeypatch.setattr(health_module, "STORE_PROBE_TIMEOUT_S", 0.5)
    try:
        start = time.monotonic()
        with pytest.raises(Exception):
            await health_module._probe_audit_redis()
        assert time.monotonic() - start < 3
    finally:
        await hung.aclose()
        server.close()


def test_the_app_container_reaches_hapi_postgres_by_service_name():
    # Without HAPI_DB_URL the client defaults to localhost:5433, which inside
    # the app container is nothing: batch reads and /health both failed.
    env = yaml.safe_load(COMPOSE.read_text())["services"]["app"]["environment"]
    hapi = next(e for e in env if e.startswith("HAPI_DB_URL="))

    assert "@hapi-db:5432/" in hapi
