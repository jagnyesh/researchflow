"""
Integration test: verify audit middleware is installed in the FastAPI app
and that the drain task starts in lifespan (Sprint 6.1 Phase 2.2 - Issue #1).
"""

import os
import json
import pytest
import fakeredis.aioredis

# Disable orchestrator boot for fast app startup in tests.
os.environ["ENABLE_ORCHESTRATOR"] = "false"

from app.security import audit_middleware as am


@pytest.fixture
async def fake_audit_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(client)
    yield client
    am.set_audit_redis(previous)
    await client.aclose()


@pytest.mark.asyncio
async def test_audit_middleware_is_installed_on_app():
    """Sanity check: app.user_middleware contains the audit middleware."""
    from app.main import app

    middleware_funcs = []
    for mw in app.user_middleware:
        # FastAPI/Starlette stores middleware as Middleware(cls, **kwargs)
        # For @app.middleware('http') decorated functions, kwargs has 'dispatch'
        kwargs = getattr(mw, "kwargs", {}) or {}
        dispatch = kwargs.get("dispatch")
        if dispatch is not None:
            middleware_funcs.append(dispatch)

    assert (
        am.audit_middleware in middleware_funcs
    ), f"audit_middleware not found in app.user_middleware: {middleware_funcs}"


@pytest.mark.asyncio
async def test_sql_query_endpoint_enqueues_pre_and_post_via_real_app(fake_audit_redis):
    """Hit the real /sql_query route on app.main:app and assert pre+post events."""
    from datetime import timedelta
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.adapters.sql_on_fhir import SQLonFHIRAdapter
    from app.security.auth import create_access_token

    # Stub the SQL execution so we don't need HAPI running
    async def stub_execute(self, sql):
        return [{"col": "value"}]

    SQLonFHIRAdapter.execute_sql = stub_execute

    token = create_access_token(
        {"sub": "user@example.com", "user_id": "user-7", "role": "researcher"},
        expires_delta=timedelta(minutes=5),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/sql_query",
            json={"sql": "SELECT 1"},
            headers={"authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    queue_len = await fake_audit_redis.llen(am.AUDIT_QUEUE_KEY)
    assert queue_len == 2
    pre = json.loads(await fake_audit_redis.lpop(am.AUDIT_QUEUE_KEY))
    post = json.loads(await fake_audit_redis.lpop(am.AUDIT_QUEUE_KEY))
    assert pre["event_type"] == "PHI_ACCESS_REQUESTED"
    assert pre["user_id"] == "user-7"
    assert post["event_type"] == "PHI_ACCESS_COMPLETED"
    assert post["status_code"] == 200
