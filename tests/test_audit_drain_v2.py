"""
Tests for the at-least-once drain (Sprint 6.1 Phase 2.2 - Issue #3).

Covers:
- BLMOVE-based pop with audit:processing list (at-least-once)
- Size-or-timeout batching
- Lifespan recovery sweep moving orphaned audit:processing back to audit:queue
- Poison-pill: bad row routed to audit:dead_letter, pipeline continues
"""

import json
import pytest
import fakeredis.aioredis
from datetime import datetime
from sqlalchemy import select

from app.security.audit_drain import (
    AUDIT_QUEUE_KEY,
    AUDIT_PROCESSING_KEY,
    AUDIT_DEAD_LETTER_KEY,
    drain_batch,
    recovery_sweep,
)
from app.database import get_db_session
from app.database.models import AuditLog


@pytest.fixture
async def fake_audit_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


def _payload(user_id="u-1", route="/sql_query", status=200, **extra):
    p = {
        "schema_version": 1,
        "event_type": "PHI_ACCESS_COMPLETED",
        "phase": "completed",
        "user_id": user_id,
        "method": "POST",
        "route_template": route,
        "status_code": status,
        "latency_ms": 5,
        "resource_type": "Query",
        "resource_id": None,
        "timestamp": datetime.utcnow().isoformat(),
    }
    p.update(extra)
    return p


# --- drain_batch happy path ---


@pytest.mark.asyncio
async def test_drain_batch_returns_zero_on_empty_queue(fake_audit_redis, clean_database):
    n = await drain_batch(fake_audit_redis, batch_size=10, block_timeout_sec=1)
    assert n == 0


@pytest.mark.asyncio
async def test_drain_batch_inserts_single_event_and_clears_processing(
    fake_audit_redis, clean_database
):
    await fake_audit_redis.rpush(AUDIT_QUEUE_KEY, json.dumps(_payload()))

    n = await drain_batch(fake_audit_redis, batch_size=10, block_timeout_sec=1)

    assert n == 1
    assert await fake_audit_redis.llen(AUDIT_QUEUE_KEY) == 0
    assert await fake_audit_redis.llen(AUDIT_PROCESSING_KEY) == 0
    async with get_db_session() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_drain_batch_handles_multiple_events_atomically(fake_audit_redis, clean_database):
    for i in range(5):
        await fake_audit_redis.rpush(AUDIT_QUEUE_KEY, json.dumps(_payload(user_id=f"u-{i}")))

    n = await drain_batch(fake_audit_redis, batch_size=10, block_timeout_sec=1)

    assert n == 5
    assert await fake_audit_redis.llen(AUDIT_QUEUE_KEY) == 0
    assert await fake_audit_redis.llen(AUDIT_PROCESSING_KEY) == 0
    async with get_db_session() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_drain_batch_respects_batch_size(fake_audit_redis, clean_database):
    for i in range(5):
        await fake_audit_redis.rpush(AUDIT_QUEUE_KEY, json.dumps(_payload(user_id=f"u-{i}")))

    n = await drain_batch(fake_audit_redis, batch_size=3, block_timeout_sec=1)

    assert n == 3
    assert await fake_audit_redis.llen(AUDIT_QUEUE_KEY) == 2


# --- recovery sweep ---


@pytest.mark.asyncio
async def test_recovery_sweep_returns_zero_when_processing_empty(fake_audit_redis):
    n = await recovery_sweep(fake_audit_redis)
    assert n == 0


@pytest.mark.asyncio
async def test_recovery_sweep_moves_orphaned_entries_back_to_queue(fake_audit_redis):
    # Simulate a previous drain that crashed mid-batch: items stuck in processing.
    await fake_audit_redis.rpush(AUDIT_PROCESSING_KEY, json.dumps(_payload(user_id="orphan-1")))
    await fake_audit_redis.rpush(AUDIT_PROCESSING_KEY, json.dumps(_payload(user_id="orphan-2")))

    n = await recovery_sweep(fake_audit_redis)

    assert n == 2
    assert await fake_audit_redis.llen(AUDIT_PROCESSING_KEY) == 0
    assert await fake_audit_redis.llen(AUDIT_QUEUE_KEY) == 2


# --- poison-pill: bad payload goes to dead-letter, batch continues ---


@pytest.mark.asyncio
async def test_drain_batch_routes_invalid_json_to_dead_letter(fake_audit_redis, clean_database):
    await fake_audit_redis.rpush(AUDIT_QUEUE_KEY, json.dumps(_payload(user_id="good-1")))
    await fake_audit_redis.rpush(AUDIT_QUEUE_KEY, "{ not valid json ")  # poison pill
    await fake_audit_redis.rpush(AUDIT_QUEUE_KEY, json.dumps(_payload(user_id="good-2")))

    n = await drain_batch(fake_audit_redis, batch_size=10, block_timeout_sec=1)

    assert n == 2  # only 2 valid events made it to Postgres
    assert await fake_audit_redis.llen(AUDIT_PROCESSING_KEY) == 0
    assert await fake_audit_redis.llen(AUDIT_DEAD_LETTER_KEY) == 1
    dead_entry = json.loads(await fake_audit_redis.lpop(AUDIT_DEAD_LETTER_KEY))
    assert "error" in dead_entry
    assert dead_entry["payload"] == "{ not valid json "


# --- supervisor: drain crash bumps restart_count, loop continues ---


@pytest.mark.asyncio
async def test_audit_drain_loop_restarts_on_crash_and_increments_counter(
    monkeypatch, fake_audit_redis
):
    import asyncio
    from app.security import audit_drain as ad

    # Reset state for the test
    ad._drain_state["restart_count"] = 0
    ad._drain_state["last_success_monotonic"] = None

    call_count = {"n": 0}

    async def boom_then_succeed(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated drain crash")
        # Subsequent calls: act like a no-op success
        return 0

    monkeypatch.setattr(ad, "drain_batch", boom_then_succeed)

    stop = asyncio.Event()
    task = asyncio.create_task(
        ad.audit_drain_loop(fake_audit_redis, stop_event=stop, block_timeout_sec=0.1)
    )
    # Allow the supervisor to crash once and start its backoff
    await asyncio.sleep(0.2)
    stop.set()
    await asyncio.wait_for(task, timeout=5)

    assert call_count["n"] >= 1
    assert ad._drain_state["restart_count"] >= 1
