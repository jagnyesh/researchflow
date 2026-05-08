"""
Tests for /health/ready audit pipeline integration (Sprint 6.1 Phase 2.2 - Issue #3).

The endpoint must surface drain liveness + queue depth and return 503 when
the audit pipeline is unhealthy (Redis unreachable, queue too deep, or drain stale).
"""

import json
import time
import pytest
import fakeredis.aioredis
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from app.api.health import router as health_router, audit_health_check
from app.security import audit_middleware as am
from app.security.audit_drain import (
    AUDIT_QUEUE_KEY,
    AUDIT_PROCESSING_KEY,
    _drain_state,
)


@pytest.fixture
async def fake_audit_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(client)
    yield client
    am.set_audit_redis(previous)
    await client.aclose()


@pytest.fixture(autouse=True)
def reset_drain_state():
    saved = dict(_drain_state)
    yield
    _drain_state.clear()
    _drain_state.update(saved)


# --- audit_health_check unit tests ---


@pytest.mark.asyncio
async def test_audit_health_check_returns_unreachable_when_redis_unset():
    am.set_audit_redis(None)
    result = await audit_health_check()
    assert result["audit_redis"] == "unreachable"
    assert result["healthy"] is False


@pytest.mark.asyncio
async def test_audit_health_check_returns_ok_when_drain_recently_succeeded(fake_audit_redis):
    _drain_state["last_success_monotonic"] = time.monotonic()
    _drain_state["restart_count"] = 0
    result = await audit_health_check()
    assert result["audit_redis"] == "ok"
    assert result["audit_queue_depth"] == 0
    assert result["audit_processing_depth"] == 0
    assert result["drain_restart_count"] == 0
    assert result["healthy"] is True


@pytest.mark.asyncio
async def test_audit_health_check_unhealthy_when_drain_stale(fake_audit_redis):
    _drain_state["last_success_monotonic"] = time.monotonic() - 60  # 60s ago
    _drain_state["restart_count"] = 0
    result = await audit_health_check(staleness_threshold_sec=30)
    assert result["healthy"] is False
    assert result["drain_last_success_seconds_ago"] >= 30


@pytest.mark.asyncio
async def test_audit_health_check_unhealthy_when_queue_too_deep(fake_audit_redis):
    _drain_state["last_success_monotonic"] = time.monotonic()
    for _ in range(15):
        await fake_audit_redis.rpush(AUDIT_QUEUE_KEY, "{}")
    result = await audit_health_check(queue_depth_threshold=10)
    assert result["healthy"] is False
    assert result["audit_queue_depth"] == 15


# --- /health/ready integration ---


@pytest.fixture
def health_app():
    app = FastAPI()
    app.include_router(health_router)
    return app


@pytest.mark.asyncio
async def test_public_ready_endpoint_returns_503_when_audit_redis_unreachable(health_app):
    """Public /health/ready still 503s on unhealthy audit pipeline — but only signals it via status, not via leaked metrics."""
    am.set_audit_redis(None)
    transport = ASGITransport(app=health_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not ready"


@pytest.mark.asyncio
async def test_public_ready_endpoint_does_not_leak_audit_internals(fake_audit_redis, health_app):
    """Finding 2: public probe must not expose drain restart count, queue depth,
    or any other intel an attacker could use to time activity to a degraded
    audit pipeline. Detailed payload is auth-gated at /health/ready/detailed.
    """
    _drain_state["last_success_monotonic"] = time.monotonic()
    transport = ASGITransport(app=health_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")
    body = response.json()
    leaky = {
        "audit_redis",
        "audit_queue_depth",
        "audit_processing_depth",
        "drain_last_success_seconds_ago",
        "drain_restart_count",
        "components",
    }
    leaked = leaky & set(body.keys())
    assert not leaked, f"public /health/ready must not leak {leaked}"
    assert body.keys() == {"status", "timestamp"}


# --- Two-tier health check (Finding 2 fix): public boolean vs auth-gated detail ---


@pytest.mark.asyncio
async def test_detailed_health_endpoint_requires_auth(fake_audit_redis):
    """`/health/ready/detailed` must be gated by auth — only operators see internals."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready/detailed")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_detailed_health_endpoint_returns_full_payload_when_authed(fake_audit_redis):
    """With valid auth, `/health/ready/detailed` returns the full audit pipeline state."""
    from datetime import timedelta
    from app.main import app
    from app.security.auth import create_access_token

    _drain_state["last_success_monotonic"] = time.monotonic()
    token = create_access_token(
        {"sub": "ops@example.com", "user_id": "ops-1", "role": "admin"},
        expires_delta=timedelta(minutes=5),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/health/ready/detailed",
            headers={"authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, f"got {response.status_code}: {response.text}"
    body = response.json()
    assert "audit_redis" in body
    assert "audit_queue_depth" in body
    assert "audit_processing_depth" in body
    assert "drain_last_success_seconds_ago" in body
    assert "drain_restart_count" in body
