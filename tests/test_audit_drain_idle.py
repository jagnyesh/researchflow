"""#269: an idle audit drain polls quietly and readiness stays 200.

Against the real audit Redis (:6380), on DB 15 so these tests never consume
another run's audit events. The client is built the way app/main.py builds
it (socket_timeout=5); the bug only shows against a real socket timeout.
"""

import asyncio
import json
import socket
import time

import pytest
import redis.asyncio as redis_async

from app.api.health import audit_health_check
from app.database import init_db
from app.security import audit_drain, audit_middleware as am
from app.security.audit_drain import AUDIT_QUEUE_KEY, audit_drain_loop


def _audit_redis_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 6380), timeout=0.5):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.requires_services,
    pytest.mark.skipif(not _audit_redis_reachable(), reason="redis-audit (:6380) not running"),
]

MAIN_SOCKET_TIMEOUT = 5  # app/main.py's audit client


@pytest.fixture
async def audit_redis():
    await init_db()
    client = redis_async.from_url(
        "redis://localhost:6380/15",
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=MAIN_SOCKET_TIMEOUT,
    )
    await client.flushdb()
    previous = am._audit_redis
    am.set_audit_redis(client)
    audit_drain._drain_state.update(last_success_monotonic=None, restart_count=0)
    yield client
    am.set_audit_redis(previous)
    await client.flushdb()
    await client.aclose()


async def _run_loop_for(client, seconds: float) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(audit_drain_loop(client, stop))
    await asyncio.sleep(seconds)
    stop.set()
    await asyncio.wait_for(task, timeout=MAIN_SOCKET_TIMEOUT + 5)


@pytest.mark.asyncio
async def test_idle_drain_does_not_crash(audit_redis):
    # Longer than the socket timeout: BLMOVE must return before the socket gives up.
    await _run_loop_for(audit_redis, MAIN_SOCKET_TIMEOUT + 3)

    assert audit_drain.get_drain_state()["restart_count"] == 0


def _event() -> str:
    return json.dumps(
        am._make_payload(
            event_type="PHI_ACCESS_REQUESTED",
            phase="requested",
            user_id="USR-269",
            method="GET",
            route_template="/research/",
            status_code=None,
            latency_ms=None,
        )
    )


@pytest.mark.asyncio
async def test_readiness_stays_healthy_while_the_drain_idles(audit_redis):
    await audit_redis.rpush(AUDIT_QUEUE_KEY, _event())

    # One event drained, then idle well past the staleness threshold.
    await _run_loop_for(audit_redis, 8)

    assert await audit_redis.llen(AUDIT_QUEUE_KEY) == 0, "the event should have drained"
    health = await audit_health_check(staleness_threshold_sec=4)
    assert health["healthy"], health


@pytest.mark.asyncio
async def test_readiness_still_fails_when_the_queue_backs_up(audit_redis):
    await audit_redis.rpush(AUDIT_QUEUE_KEY, *[_event() for _ in range(3)])
    audit_drain._drain_state["last_success_monotonic"] = None

    health = await audit_health_check(queue_depth_threshold=2)

    assert not health["healthy"]


@pytest.mark.asyncio
async def test_readiness_still_fails_when_audit_redis_is_unreachable(audit_redis):
    unreachable = redis_async.from_url(
        "redis://127.0.0.1:1/0", socket_connect_timeout=0.5, socket_timeout=0.5
    )
    am.set_audit_redis(unreachable)
    try:
        health = await audit_health_check()
    finally:
        await unreachable.aclose()

    assert health["audit_redis"] == "unreachable"
    assert not health["healthy"]


@pytest.mark.asyncio
async def test_readiness_fails_when_audit_writes_keep_failing(audit_redis, monkeypatch):
    # A non-IntegrityError write failure crashes the batch and strands the event
    # in audit:processing; later empty polls must not mark the drain healthy.
    def failing_write(_payload):
        raise RuntimeError("audit_logs insert failed")

    monkeypatch.setattr(audit_drain, "_payload_to_audit_log", failing_write)
    # A drain that was healthy, then started failing (a never-succeeded drain is
    # treated as starting up; that's the health check's existing grace).
    audit_drain._drain_state["last_success_monotonic"] = time.monotonic()
    await audit_redis.rpush(AUDIT_QUEUE_KEY, _event())

    await _run_loop_for(audit_redis, 8)

    assert await audit_redis.llen(audit_drain.AUDIT_PROCESSING_KEY) == 1
    health = await audit_health_check(staleness_threshold_sec=4)
    assert not health["healthy"], health
