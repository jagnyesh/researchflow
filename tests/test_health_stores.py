"""#274: /health covers the stores the app reads, and compose keeps them up.

Real connections; unreachable stores are real closed ports, not stubs.
"""

import ast
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.health import router as health_router

COMPOSE = Path(__file__).resolve().parent.parent / "config/docker-compose.yml"
APP = COMPOSE.parent.parent / "app"
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


@pytest.mark.asyncio
async def test_health_probes_the_fhir_server_named_by_fhir_server_url(monkeypatch):
    # #312: /health read FHIR_BASE_URL, which nothing sets, so in the container
    # it probed localhost:8081. A stub records the request, so a live HAPI on
    # 8081 can't make this pass.
    import asyncio

    requested = []

    async def capability_statement(reader, writer):
        requested.append((await reader.readline()).decode())
        body = b'{"resourceType": "CapabilityStatement"}'
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/fhir+json\r\n"
            b"Content-Length: %d\r\nConnection: close\r\n\r\n%s" % (len(body), body)
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(capability_statement, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        body, text = await _health(monkeypatch, FHIR_SERVER_URL=f"http://127.0.0.1:{port}/fhir")
    finally:
        server.close()

    assert any(line.startswith("GET /fhir/metadata ") for line in requested)
    assert body["components"]["fhir_server"] == {"status": "healthy"}
    assert f"127.0.0.1:{port}" not in text


def test_the_app_container_reaches_hapi_postgres_by_service_name():
    # Without HAPI_DB_URL the client defaults to localhost:5433, which inside
    # the app container is nothing: batch reads and /health both failed.
    env = yaml.safe_load(COMPOSE.read_text())["services"]["app"]["environment"]
    hapi = next(e for e in env if e.startswith("HAPI_DB_URL="))

    assert "@hapi-db:5432/" in hapi


def _compose_app_env():
    env = yaml.safe_load(COMPOSE.read_text())["services"]["app"]["environment"]
    return dict(entry.split("=", 1) for entry in env)


def _store_urls_the_app_reads():
    # Any string literal named like a store URL counts as a read, so aliased
    # getenv, keyword args and name constants can't slip past. The Streamlit
    # dashboards in app/web_ui/ don't run in the compose app container.
    store = re.compile(r"DATABASE_URL|[A-Z0-9_]*_DB_URL|FHIR_[A-Z0-9_]*URL|REDIS[A-Z0-9_]*_URL")
    names = set()
    for path in APP.rglob("*.py"):
        if "web_ui" not in path.relative_to(APP).parts:
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if store.fullmatch(node.value):
                        names.add(node.value)
    return names


def test_compose_sets_every_store_url_the_app_reads_to_a_compose_service():
    # #312, the same class as #274: a store URL the code reads but compose
    # doesn't set falls back to localhost, or to HAPI's full-privilege user.
    names = _store_urls_the_app_reads()
    env = _compose_app_env()
    services = set(yaml.safe_load(COMPOSE.read_text())["services"])

    # A floor, so a scan that silently finds nothing can't pass.
    assert names >= {"DATABASE_URL", "HAPI_DB_URL", "EXPLORATORY_DB_URL", "FHIR_SERVER_URL"}
    assert sorted(names - env.keys()) == []
    hosts = {name: urlsplit(env[name]).hostname for name in names}
    assert {n: h for n, h in hosts.items() if h not in services} == {}


@pytest.mark.parametrize("name", ["DATABASE_URL", "HAPI_DB_URL"])
def test_the_async_engines_accept_the_compose_database_urls(name):
    # get_engine() and get_hapi_engine() pass these straight to
    # create_async_engine, which rejects a bare postgresql:// (no async driver).
    from sqlalchemy.ext.asyncio import create_async_engine

    create_async_engine(_compose_app_env()[name]).sync_engine.dispose()


def test_compose_runs_exploratory_sql_as_the_role_hapi_db_creates():
    # ADR 0028/0034: synthesized SQL runs as rf_readonly, never as hapi. The
    # credentials must match what hapi-db's initdb script creates.
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    mount = next(v for v in services["hapi-db"]["volumes"] if "/docker-entrypoint-initdb.d/" in v)
    role_sql = (COMPOSE.parent / mount.split(":")[0]).read_text()
    role, password = re.search(r"CREATE ROLE (\w+) LOGIN PASSWORD '([^']*)'", role_sql).groups()
    url = urlsplit(_compose_app_env()["EXPLORATORY_DB_URL"])

    assert role == "rf_readonly"
    assert (url.username, url.password, url.path) == (role, password, "/hapi")
    assert (url.hostname, url.port) == ("hapi-db", 5432)
