"""
Tests for audit drain task (Sprint 6.1 Phase 2.2 - Issue #1)
"""

import json
import pytest
import fakeredis.aioredis
from datetime import datetime
from sqlalchemy import select

from app.security.audit_drain import process_one_audit_event
from app.database import get_db_session
from app.database.models import AuditLog


@pytest.fixture
async def fake_audit_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_process_one_audit_event_inserts_row(fake_audit_redis, clean_database):
    payload = {
        "user_id": "user-123",
        "method": "POST",
        "route_template": "/sql_query",
        "status_code": 200,
        "timestamp": datetime.utcnow().isoformat(),
    }
    await fake_audit_redis.rpush("audit:queue", json.dumps(payload))

    processed = await process_one_audit_event(fake_audit_redis)

    assert processed is True
    async with get_db_session() as session:
        result = await session.execute(select(AuditLog))
        rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == "user-123"
    assert rows[0].event_data["method"] == "POST"
    assert rows[0].event_data["route_template"] == "/sql_query"
    assert rows[0].phi_accessed is True


@pytest.mark.asyncio
async def test_process_one_audit_event_empty_queue_returns_false(fake_audit_redis, clean_database):
    processed = await process_one_audit_event(fake_audit_redis)
    assert processed is False


@pytest.mark.asyncio
async def test_process_one_audit_event_uses_payload_event_type(fake_audit_redis, clean_database):
    """Issue #2 emits typed events (PHI_ACCESS_REQUESTED etc.); drain must respect them."""
    payload = {
        "event_type": "PHI_ACCESS_REQUESTED",
        "phase": "requested",
        "user_id": "user-x",
        "method": "POST",
        "route_template": "/sql_query",
        "status_code": None,
        "timestamp": datetime.utcnow().isoformat(),
    }
    await fake_audit_redis.rpush("audit:queue", json.dumps(payload))

    processed = await process_one_audit_event(fake_audit_redis)

    assert processed is True
    async with get_db_session() as session:
        result = await session.execute(select(AuditLog))
        rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == "PHI_ACCESS_REQUESTED"


@pytest.mark.asyncio
async def test_process_one_audit_event_handles_null_user_id(fake_audit_redis, clean_database):
    payload = {
        "user_id": None,
        "method": "GET",
        "route_template": "/sql_query",
        "status_code": 401,
        "timestamp": datetime.utcnow().isoformat(),
    }
    await fake_audit_redis.rpush("audit:queue", json.dumps(payload))

    processed = await process_one_audit_event(fake_audit_redis)

    assert processed is True
    async with get_db_session() as session:
        result = await session.execute(select(AuditLog))
        rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id is None
