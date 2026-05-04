"""
Audit drain task for Sprint 6.1 Phase 2.2 (Issue #1 - tracer bullet).

Pulls audit events from the Redis queue and writes them to the audit_logs table.
Issue #1 ships the simplest viable drain (LPOP loop, one event at a time).
At-least-once durability, batching, and supervision land in Issue #3.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from ..database import get_db_session
from ..database.models import AuditLog

logger = logging.getLogger(__name__)

AUDIT_QUEUE_KEY = "audit:queue"


async def process_one_audit_event(redis_client) -> bool:
    """Pop one audit event from the queue and persist it to audit_logs.

    Returns True if an event was processed, False if the queue was empty.
    """
    payload_json = await redis_client.lpop(AUDIT_QUEUE_KEY)
    if payload_json is None:
        return False

    payload = json.loads(payload_json)
    timestamp_str = payload.get("timestamp")
    timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.utcnow()

    status_code = payload.get("status_code")
    audit = AuditLog(
        timestamp=timestamp,
        user_id=payload.get("user_id"),
        event_type=payload.get("event_type", "PHI_ACCESS"),
        action=payload.get("method"),
        resource_type=payload.get("resource_type"),
        resource_id=payload.get("resource_id"),
        result=(
            "success"
            if status_code is None or status_code < 400
            else ("auth_failed" if status_code == 401 else "failure")
        ),
        ip_address=payload.get("ip_address"),
        user_agent=payload.get("user_agent"),
        phi_accessed=True,
        event_data=payload,
    )

    async with get_db_session() as session:
        session.add(audit)

    return True


async def audit_drain_loop(redis_client, stop_event: Optional[asyncio.Event] = None):
    """Background loop draining the audit queue until stop_event is set.

    Issue #1 uses a simple LPOP + sleep-on-empty pattern. Issue #3 replaces
    this with BLMOVE + at-least-once processing list semantics.
    """
    if stop_event is None:
        stop_event = asyncio.Event()

    while not stop_event.is_set():
        try:
            processed = await process_one_audit_event(redis_client)
            if not processed:
                await asyncio.sleep(0.1)
        except Exception:
            logger.exception("audit drain iteration failed")
            await asyncio.sleep(0.5)
