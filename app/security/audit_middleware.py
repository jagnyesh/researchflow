"""
Audit middleware for Sprint 6.1 Phase 2.2.

Issue #1 (committed): post-only middleware mounted on /sql_query only.
Issue #2 (in progress): default-deny classifier, middleware-side JWT decode,
fail-closed semantics, pre/post audit pair, UNAUTH_PHI_ATTEMPT events.
Issue #3: at-least-once durability via processing list.
"""

import enum
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .audit_drain import AUDIT_QUEUE_KEY
from .auth import decode_access_token
from ..a2a.auth import verify_service_token

logger = logging.getLogger(__name__)


@dataclass
class Principal:
    """Resolved authenticated identity for the audit pipeline."""

    user_id: str
    kind: str  # "user" or "service"
    email: Optional[str] = None
    role: Optional[str] = None


# Service-token routes use verify_service_token; everything else uses the
# human JWT. Cross-token use is rejected (a human JWT is not valid for /a2a).
_SERVICE_ROUTE_PREFIXES = ("/a2a", "/mcp")

# Route-template-to-resource map (Issue #2). Maps the first path segment to the
# typed AuditLog.resource_type column. Best-effort resource_id extraction from
# the second path segment; verb-style segments (execute, pending, etc.) are
# treated as non-IDs and leave resource_id null.
RESOURCE_MAP = {
    "/research": "ResearchRequest",
    "/sql_query": "Query",
    "/analytics": "AnalyticsView",
    "/approvals": "Approval",
    "/users": "User",
    "/mcp": "AgentContext",
    "/a2a": "ServiceToken",
    "/auth": "AuthEvent",
}


def _looks_like_id(segment: str) -> bool:
    """Heuristic: UUIDs have hyphens, numeric IDs are digits, opaque IDs are long."""
    if "-" in segment or segment.isdigit():
        return True
    return len(segment) > 12


def resolve_resource(path: str) -> tuple[Optional[str], Optional[str]]:
    """Best-effort (resource_type, resource_id) lookup. Returns (None, None) on miss."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None, None
    prefix = "/" + parts[0]
    resource_type = RESOURCE_MAP.get(prefix)
    if resource_type is None:
        return None, None
    if len(parts) >= 2 and _looks_like_id(parts[1]):
        return resource_type, parts[1]
    return resource_type, None


def warn_if_unmapped_phi_route(path: str) -> None:
    """Log a warning if a PHI-classified path isn't in RESOURCE_MAP."""
    if classify_route(path) is not RouteClass.PHI:
        return
    rtype, _ = resolve_resource(path)
    if rtype is None:
        logger.warning("PHI route %s missing from RESOURCE_MAP; resource_id will be null", path)


def _extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header:
        return None
    parts = auth_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def resolve_principal(request) -> Optional[Principal]:
    """Decode the Authorization header. Returns Principal or None on failure."""
    auth_header = request.headers.get("authorization")
    token = _extract_bearer(auth_header)
    if token is None:
        return None

    path = request.url.path
    if any(path == p or path.startswith(p + "/") for p in _SERVICE_ROUTE_PREFIXES):
        client_id = verify_service_token(token)
        if client_id is None:
            return None
        return Principal(user_id=client_id, kind="service")

    token_data = decode_access_token(token)
    if token_data is None or token_data.user_id is None:
        return None
    return Principal(
        user_id=token_data.user_id,
        kind="user",
        email=token_data.email,
        role=token_data.role,
    )


class RouteClass(enum.Enum):
    """Default-deny route classification (Issue #2)."""

    NO_AUDIT = "no_audit"
    NON_AUTH_AUDITED = "non_auth_audited"
    PHI = "phi"


# Routes that skip BOTH auth and audit. Liveness probes, static docs, the root
# landing page. Adding here is the only way to opt out of audit — every other
# route is treated as PHI.
NO_AUDIT_ALLOWLIST = frozenset(
    {
        "/",
        "/health",
        "/health/live",
        "/health/ready",
        "/docs",
        "/docs/",
        "/openapi.json",
        "/redoc",
    }
)

# Routes that don't require auth (you can't be authenticated to log in or
# bootstrap a service token) but still need audit. Login attempts and service
# token issuance are auditable credential events.
# Must be a strict superset of NO_AUDIT_ALLOWLIST.
NON_AUTH_ALLOWLIST = NO_AUDIT_ALLOWLIST | frozenset(
    {
        "/auth/login",
        "/auth/refresh",
        "/auth/logout",
        "/a2a/token",  # service-token issuance: chicken-and-egg, can't require a token to get one
    }
)


def classify_route(path: str) -> RouteClass:
    """Classify a request path. Default-deny: unknown paths are PHI."""
    normalized = path.rstrip("/") or "/"
    candidates = {path, normalized, normalized + "/"}

    if candidates & NO_AUDIT_ALLOWLIST:
        return RouteClass.NO_AUDIT
    if candidates & NON_AUTH_ALLOWLIST:
        return RouteClass.NON_AUTH_AUDITED
    return RouteClass.PHI


_audit_redis = None


def set_audit_redis(client):
    """Set the Redis client used for audit enqueue. None disables enqueue."""
    global _audit_redis
    _audit_redis = client


async def _try_enqueue(payload: dict) -> bool:
    """Enqueue payload to audit:queue. Returns True on success, False on failure."""
    if _audit_redis is None:
        logger.error("audit redis not configured; PHI request will fail-closed")
        return False
    try:
        await _audit_redis.rpush(AUDIT_QUEUE_KEY, json.dumps(payload))
        return True
    except Exception:
        logger.exception("audit enqueue failed; PHI request will fail-closed")
        return False


def _make_payload(
    *,
    event_type: str,
    phase: str,
    user_id: Optional[str],
    method: str,
    route_template: str,
    status_code: Optional[int],
    latency_ms: Optional[int],
) -> dict:
    resource_type, resource_id = resolve_resource(route_template)
    return {
        "schema_version": 1,
        "event_type": event_type,
        "phase": phase,
        "user_id": user_id,
        "method": method,
        "route_template": route_template,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "timestamp": datetime.utcnow().isoformat(),
    }


async def audit_middleware(request, call_next):
    """Default-deny audit middleware with pre/post pair and fail-closed gate."""
    import time
    from fastapi.responses import JSONResponse

    path = request.url.path
    klass = classify_route(path)

    if klass is RouteClass.NO_AUDIT:
        return await call_next(request)

    if klass is RouteClass.PHI:
        warn_if_unmapped_phi_route(path)

    principal = resolve_principal(request)

    if klass is RouteClass.PHI and principal is None:
        await _try_enqueue(
            _make_payload(
                event_type="UNAUTH_PHI_ATTEMPT",
                phase="unauth",
                user_id=None,
                method=request.method,
                route_template=path,
                status_code=401,
                latency_ms=None,
            )
        )
        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if principal is not None:
        request.state.principal = principal

    user_id = principal.user_id if principal else None

    pre_ok = await _try_enqueue(
        _make_payload(
            event_type="PHI_ACCESS_REQUESTED",
            phase="requested",
            user_id=user_id,
            method=request.method,
            route_template=path,
            status_code=None,
            latency_ms=None,
        )
    )
    if not pre_ok:
        return JSONResponse({"detail": "Audit pipeline unavailable"}, status_code=503)

    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = int((time.perf_counter() - start) * 1000)

    post_ok = await _try_enqueue(
        _make_payload(
            event_type="PHI_ACCESS_COMPLETED",
            phase="completed",
            user_id=user_id,
            method=request.method,
            route_template=path,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
    )
    if not post_ok:
        return JSONResponse({"detail": "Audit pipeline unavailable"}, status_code=503)

    return response
