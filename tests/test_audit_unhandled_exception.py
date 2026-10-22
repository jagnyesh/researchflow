"""Unhandled route exceptions keep the audit pair and leak nothing (#180).

The audit middleware awaited `call_next` with no `try`, so a route that
raised let the exception escape: PHI_ACCESS_COMPLETED was never enqueued
(REQUESTED with no COMPLETED — a hole in the HIPAA audit trail), and the
server's default exception logging printed the message. ADR 0029 deferred
this backstop; the per-site `internal_error` helper only covers app/api.
"""

import json
import logging
import re
from datetime import timedelta

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

PHI_NEEDLE = "patient QQ-5511 eGFR 38 on 2026-02-03"


@pytest.fixture
async def fake_audit_redis():
    from app.security import audit_middleware as am

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(client)
    yield client
    am.set_audit_redis(previous)
    await client.aclose()


@pytest.fixture
def raising_app():
    from app.security import audit_middleware as am

    app = FastAPI()
    app.middleware("http")(am.audit_middleware)

    @app.get("/zz_unhandled")
    async def boom():
        raise RuntimeError(PHI_NEEDLE)

    return app


@pytest.mark.asyncio
async def test_unhandled_exception_gets_completed_500_and_generic_body(
    fake_audit_redis, raising_app, caplog
):
    from app.security import audit_middleware as am
    from app.security.auth import create_access_token

    token = create_access_token(
        {"sub": "u@example.com", "user_id": "unh-1", "role": "researcher"},
        expires_delta=timedelta(minutes=5),
    )
    transport = ASGITransport(app=raising_app, raise_app_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/zz_unhandled", headers={"authorization": f"Bearer {token}"})

    assert resp.status_code == 500
    assert PHI_NEEDLE not in resp.text
    assert PHI_NEEDLE not in caplog.text
    ref = re.search(r"ref: ([0-9a-f]{12})", resp.json()["detail"]).group(1)
    assert ref in caplog.text

    events = []
    while (item := await fake_audit_redis.lpop(am.AUDIT_QUEUE_KEY)) is not None:
        events.append(json.loads(item))
    completed = [e for e in events if e["event_type"] == "PHI_ACCESS_COMPLETED"]
    assert [e["event_type"] for e in events].count("PHI_ACCESS_REQUESTED") == 1
    assert completed and completed[0]["status_code"] == 500


@pytest.mark.asyncio
async def test_unhandled_exception_on_no_audit_route_is_generic(fake_audit_redis, caplog):
    """Unaudited routes (health probes, docs) get the same PHI-safe 500 —
    without audit events, which they never emit."""
    from app.security import audit_middleware as am

    app = FastAPI()
    app.middleware("http")(am.audit_middleware)

    @app.get("/health/live")
    async def boom():
        raise RuntimeError(PHI_NEEDLE)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health/live")

    assert resp.status_code == 500
    assert re.search(r"ref: [0-9a-f]{12}", resp.json()["detail"])
    assert PHI_NEEDLE not in resp.text and PHI_NEEDLE not in caplog.text
    assert await fake_audit_redis.llen(am.AUDIT_QUEUE_KEY) == 0
