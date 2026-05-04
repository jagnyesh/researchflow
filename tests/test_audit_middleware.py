"""
Tests for audit middleware (Sprint 6.1 Phase 2.2 - Issue #1)
"""

import json
import pytest
import fakeredis.aioredis
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.security import audit_middleware as am


@pytest.fixture
async def fake_audit_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    am.set_audit_redis(client)
    yield client
    am.set_audit_redis(None)
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

    return app


@pytest.mark.asyncio
async def test_sql_query_request_enqueues_audit_event(fake_audit_redis, test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/sql_query", json={"sql": "SELECT 1"})

    assert response.status_code == 200
    queue_len = await fake_audit_redis.llen(am.AUDIT_QUEUE_KEY)
    assert queue_len == 1
    payload = json.loads(await fake_audit_redis.lpop(am.AUDIT_QUEUE_KEY))
    assert payload["method"] == "POST"
    assert payload["route_template"] == "/sql_query"
    assert payload["status_code"] == 200
    assert "timestamp" in payload


@pytest.mark.asyncio
async def test_non_sql_query_request_does_not_enqueue(fake_audit_redis, test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    queue_len = await fake_audit_redis.llen(am.AUDIT_QUEUE_KEY)
    assert queue_len == 0


@pytest.mark.asyncio
async def test_failed_sql_query_still_enqueues_with_error_status(fake_audit_redis, test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Empty body fails Pydantic validation -> 422
        response = await client.post("/sql_query", json={})

    assert response.status_code == 422
    queue_len = await fake_audit_redis.llen(am.AUDIT_QUEUE_KEY)
    assert queue_len == 1
    payload = json.loads(await fake_audit_redis.lpop(am.AUDIT_QUEUE_KEY))
    assert payload["status_code"] == 422
