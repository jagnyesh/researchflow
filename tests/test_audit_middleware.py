"""
Tests for the rewritten audit middleware (Sprint 6.1 Phase 2.2 - Issue #2).

Issue #2 supersedes Issue #1's tracer-bullet middleware. Behavior:
- default-deny classifier (everything is PHI unless allowlisted)
- middleware-side JWT/service-token decode
- pre-event before handler runs (with user_id)
- fail-closed 5xx on PHI when Redis enqueue fails
- UNAUTH_PHI_ATTEMPT + 401 for unauthenticated PHI access
- post-event after handler with status_code + latency_ms
"""

import json
import pytest
import fakeredis.aioredis
from datetime import timedelta
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.security import audit_middleware as am
from app.security.auth import create_access_token


@pytest.fixture
async def fake_audit_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(client)
    yield client
    am.set_audit_redis(previous)
    await client.aclose()


@pytest.fixture
def test_app():
    from pydantic import BaseModel

    app = FastAPI()
    app.middleware("http")(am.audit_middleware)

    class SQLBody(BaseModel):
        sql: str

    @app.post("/sql_query")
    async def sql_query(body: SQLBody):
        return {"rows": []}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/auth/login")
    async def login():
        return {"token": "stub"}

    return app


def _user_jwt(user_id: str = "user-42") -> str:
    return create_access_token(
        {"sub": "user@example.com", "user_id": user_id, "role": "researcher"},
        expires_delta=timedelta(minutes=5),
    )


async def _drain_payloads(redis_client) -> list[dict]:
    out = []
    while True:
        item = await redis_client.lpop(am.AUDIT_QUEUE_KEY)
        if item is None:
            break
        out.append(json.loads(item))
    return out


# --- PHI route, authenticated: pre + post pair ---


@pytest.mark.asyncio
async def test_phi_route_authenticated_emits_pre_and_post_events(fake_audit_redis, test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/sql_query",
            json={"sql": "SELECT 1"},
            headers={"authorization": f"Bearer {_user_jwt()}"},
        )

    assert response.status_code == 200
    events = await _drain_payloads(fake_audit_redis)
    assert len(events) == 2

    pre, post = events
    assert pre["event_type"] == "PHI_ACCESS_REQUESTED"
    assert pre["phase"] == "requested"
    assert pre["user_id"] == "user-42"
    assert pre["status_code"] is None

    assert post["event_type"] == "PHI_ACCESS_COMPLETED"
    assert post["phase"] == "completed"
    assert post["user_id"] == "user-42"
    assert post["status_code"] == 200
    assert isinstance(post["latency_ms"], (int, float))
    assert pre["schema_version"] == 1
    assert post["schema_version"] == 1


# --- PHI route, no auth: UNAUTH event + 401, handler NOT called ---


@pytest.mark.asyncio
async def test_phi_route_unauthenticated_emits_unauth_attempt_and_401(fake_audit_redis, test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/sql_query", json={"sql": "SELECT 1"})

    assert response.status_code == 401
    events = await _drain_payloads(fake_audit_redis)
    assert len(events) == 1
    assert events[0]["event_type"] == "UNAUTH_PHI_ATTEMPT"
    assert events[0]["user_id"] is None
    assert events[0]["route_template"] == "/sql_query"


@pytest.mark.asyncio
async def test_phi_route_invalid_token_emits_unauth_attempt_and_401(fake_audit_redis, test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/sql_query",
            json={"sql": "SELECT 1"},
            headers={"authorization": "Bearer total-garbage"},
        )

    assert response.status_code == 401
    events = await _drain_payloads(fake_audit_redis)
    assert len(events) == 1
    assert events[0]["event_type"] == "UNAUTH_PHI_ATTEMPT"


# --- NO_AUDIT route: no events, no auth required ---


@pytest.mark.asyncio
async def test_health_route_emits_no_events(fake_audit_redis, test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    events = await _drain_payloads(fake_audit_redis)
    assert events == []


# --- NON_AUTH_AUDITED route (/auth/login): audited, no auth required ---


@pytest.mark.asyncio
async def test_login_route_audited_without_auth(fake_audit_redis, test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/auth/login")

    assert response.status_code == 200
    events = await _drain_payloads(fake_audit_redis)
    assert len(events) == 2
    assert events[0]["event_type"] == "PHI_ACCESS_REQUESTED"
    assert events[0]["user_id"] is None
    assert events[1]["event_type"] == "PHI_ACCESS_COMPLETED"
    assert events[1]["status_code"] == 200


# --- Fail-closed: Redis down on a PHI route -> 503, handler NOT called ---


@pytest.mark.asyncio
async def test_phi_route_fail_closed_when_audit_redis_unreachable(test_app):
    """If audit redis isn't set, PHI requests must 5xx without running the handler."""
    previous = am._audit_redis
    am.set_audit_redis(None)
    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/sql_query",
                json={"sql": "SELECT 1"},
                headers={"authorization": f"Bearer {_user_jwt()}"},
            )
        assert response.status_code == 503
    finally:
        am.set_audit_redis(previous)


# --- Fail-closed: enqueue raises an exception -> 503 ---


class _BoomRedis:
    """Stub that raises on every rpush — simulates Redis OOM / network failure."""

    async def rpush(self, *_a, **_kw):
        raise RuntimeError("redis exploded")


@pytest.mark.asyncio
async def test_phi_route_fail_closed_when_rpush_raises(test_app):
    previous = am._audit_redis
    am.set_audit_redis(_BoomRedis())
    try:
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/sql_query",
                json={"sql": "SELECT 1"},
                headers={"authorization": f"Bearer {_user_jwt()}"},
            )
        assert response.status_code == 503
    finally:
        am.set_audit_redis(previous)


# --- Principal landed on request.state for handler to read ---


@pytest.mark.asyncio
async def test_principal_is_attached_to_request_state(fake_audit_redis):
    captured = {}

    app = FastAPI()
    app.middleware("http")(am.audit_middleware)

    @app.get("/whoami")
    async def whoami(request_):
        from fastapi import Request

    from fastapi import Request

    @app.get("/whoami2")
    async def whoami2(request: Request):
        principal = getattr(request.state, "principal", None)
        captured["principal"] = principal
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/whoami2", headers={"authorization": f"Bearer {_user_jwt('user-99')}"}
        )

    assert response.status_code == 200
    assert captured["principal"] is not None
    assert captured["principal"].user_id == "user-99"
