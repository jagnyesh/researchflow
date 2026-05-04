"""
Audit drain task for Sprint 6.1 Phase 2.2.

Issue #1: simple LPOP-based drain (process_one_audit_event).
Issue #2: drain reads typed event_type from payload.
Issue #3: at-least-once via BLMOVE + audit:processing list, size-or-timeout
batching, lifespan recovery sweep, poison-pill -> audit:dead_letter.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError

from ..database import get_db_session
from ..database.models import AuditLog

logger = logging.getLogger(__name__)

AUDIT_QUEUE_KEY = "audit:queue"
AUDIT_PROCESSING_KEY = "audit:processing"
AUDIT_DEAD_LETTER_KEY = "audit:dead_letter"


# Drain liveness state for /health/ready (Issue #3).
_drain_state = {
    "last_success_monotonic": None,
    "restart_count": 0,
}


def get_drain_state() -> dict:
    """Snapshot of drain liveness for /health/ready."""
    return dict(_drain_state)


def _result_for_status(status_code: Optional[int]) -> str:
    if status_code is None or status_code < 400:
        return "success"
    if status_code == 401:
        return "auth_failed"
    return "failure"


def _payload_to_audit_log(payload: dict) -> AuditLog:
    timestamp_str = payload.get("timestamp")
    timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.utcnow()
    return AuditLog(
        timestamp=timestamp,
        user_id=payload.get("user_id"),
        event_type=payload.get("event_type", "PHI_ACCESS"),
        action=payload.get("method"),
        resource_type=payload.get("resource_type"),
        resource_id=payload.get("resource_id"),
        result=_result_for_status(payload.get("status_code")),
        ip_address=payload.get("ip_address"),
        user_agent=payload.get("user_agent"),
        phi_accessed=True,
        event_data=payload,
    )


# ---------------------------------------------------------------------------
# Issue #1 / #2 single-event drain. Kept for back-compat with tracer-bullet
# tests; production runs drain_batch via audit_drain_loop.
# ---------------------------------------------------------------------------


async def process_one_audit_event(redis_client) -> bool:
    """Pop one audit event and persist it. Returns True if processed."""
    payload_json = await redis_client.lpop(AUDIT_QUEUE_KEY)
    if payload_json is None:
        return False
    payload = json.loads(payload_json)
    audit = _payload_to_audit_log(payload)
    async with get_db_session() as session:
        session.add(audit)
    return True


# ---------------------------------------------------------------------------
# Issue #3 at-least-once drain
# ---------------------------------------------------------------------------


async def _send_to_dead_letter(redis_client, raw: str, error: str) -> None:
    entry = json.dumps({"error": error, "payload": raw})
    await redis_client.rpush(AUDIT_DEAD_LETTER_KEY, entry)


async def _ack(redis_client, raw: str) -> None:
    """Remove raw entry from processing list (one occurrence)."""
    await redis_client.lrem(AUDIT_PROCESSING_KEY, 1, raw)


async def drain_batch(redis_client, batch_size: int = 100, block_timeout_sec: float = 5) -> int:
    """Drain a batch from audit:queue. At-least-once via processing list.

    Returns the number of events successfully written to audit_logs.
    Bad payloads (invalid JSON, mapping errors) are routed to audit:dead_letter
    and counted as 'handled' but not as 'written'.
    """
    first = await redis_client.blmove(
        AUDIT_QUEUE_KEY, AUDIT_PROCESSING_KEY, timeout=block_timeout_sec
    )
    if first is None:
        return 0

    raw_entries = [first]
    while len(raw_entries) < batch_size:
        more = await redis_client.lmove(AUDIT_QUEUE_KEY, AUDIT_PROCESSING_KEY)
        if more is None:
            break
        raw_entries.append(more)

    parsed: list[tuple[str, dict]] = []
    for raw in raw_entries:
        try:
            parsed.append((raw, json.loads(raw)))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("audit drain: invalid JSON in queue, dead-lettering")
            await _send_to_dead_letter(redis_client, raw, repr(exc))
            await _ack(redis_client, raw)

    if not parsed:
        return 0

    written = 0
    try:
        async with get_db_session() as session:
            for _raw, payload in parsed:
                session.add(_payload_to_audit_log(payload))
        # If we got here, the bulk insert (auto-flushed on commit) succeeded.
        for raw, _payload in parsed:
            await _ack(redis_client, raw)
        written = len(parsed)
    except IntegrityError:
        logger.warning("audit drain: bulk insert IntegrityError, falling back to per-row")
        for raw, payload in parsed:
            try:
                async with get_db_session() as session:
                    session.add(_payload_to_audit_log(payload))
                await _ack(redis_client, raw)
                written += 1
            except IntegrityError as exc:
                logger.warning("audit drain: row failed, dead-lettering")
                await _send_to_dead_letter(redis_client, raw, repr(exc))
                await _ack(redis_client, raw)

    if written > 0:
        _drain_state["last_success_monotonic"] = time.monotonic()

    return written


async def recovery_sweep(redis_client) -> int:
    """Move all entries from audit:processing back to audit:queue.

    Run on lifespan startup to recover from drain crashes mid-batch in a
    previous process. Returns count of entries recovered.
    """
    count = 0
    while True:
        # Move from tail of processing back to head of queue (preserve order
        # roughly; recovery isn't strict FIFO and dupes are acceptable per Q4).
        item = await redis_client.lmove(
            AUDIT_PROCESSING_KEY, AUDIT_QUEUE_KEY, src="LEFT", dest="LEFT"
        )
        if item is None:
            break
        count += 1
    if count > 0:
        logger.warning("audit drain: recovery sweep moved %d orphaned entries back to queue", count)
    return count


async def audit_drain_loop(
    redis_client,
    stop_event: Optional[asyncio.Event] = None,
    batch_size: int = 100,
    block_timeout_sec: float = 5,
):
    """Background drain loop. Issue #3: supervised, at-least-once."""
    if stop_event is None:
        stop_event = asyncio.Event()

    attempts = 0
    while not stop_event.is_set():
        try:
            await drain_batch(
                redis_client,
                batch_size=batch_size,
                block_timeout_sec=block_timeout_sec,
            )
            attempts = 0  # reset backoff on any successful loop iteration
        except Exception:
            attempts += 1
            backoff = min(60, 2**attempts)
            _drain_state["restart_count"] += 1
            logger.exception(
                "audit drain crashed; restart_count=%d, sleeping %.1fs",
                _drain_state["restart_count"],
                backoff,
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
