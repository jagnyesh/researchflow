"""
Audit middleware for Sprint 6.1 Phase 2.2 (Issue #1 - tracer bullet).

Issue #1 ships post-only middleware mounted on /sql_query only. Default-deny
classification, JWT decode, fail-closed semantics, and pre/post audit pairs
land in Issue #2. At-least-once durability lands in Issue #3.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from .audit_drain import AUDIT_QUEUE_KEY

logger = logging.getLogger(__name__)

# Issue #1: only this path is audited. Issue #2 replaces with default-deny classifier.
_TRACER_BULLET_PATHS = {"/sql_query"}

_audit_redis = None


def set_audit_redis(client):
    """Set the Redis client used for audit enqueue. None disables enqueue."""
    global _audit_redis
    _audit_redis = client


async def audit_middleware(request, call_next):
    """Post-handler audit middleware. Issue #1 fail-open on enqueue failure."""
    response = await call_next(request)

    if request.url.path not in _TRACER_BULLET_PATHS:
        return response

    if _audit_redis is None:
        logger.warning("audit redis not configured; skipping enqueue")
        return response

    payload = {
        "user_id": None,  # Issue #2 wires JWT decode
        "method": request.method,
        "route_template": request.url.path,
        "status_code": response.status_code,
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        await _audit_redis.rpush(AUDIT_QUEUE_KEY, json.dumps(payload))
    except Exception:
        logger.exception("audit enqueue failed (Issue #1: fail-open)")

    return response
