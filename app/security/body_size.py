"""Request-body size limit middleware (CSO Phase 2.3 Finding 1 fix, layer 2).

Catches oversized requests at the request boundary so they never reach Pydantic.
Without this, an authenticated attacker could submit a 100MB body containing a
single dict with one giant string value, bypassing LongText caps and causing
memory exhaustion.

Runs BEFORE the audit middleware so 413-rejected requests don't pollute audit
volume — body-size attacks are infrastructure noise, not auditable PHI events.
"""

import logging
import os

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Default 1MB. Generous for legitimate research request bodies; tight enough to
# bound memory pressure from a single attacker connection.
MAX_REQUEST_BODY_BYTES = int(os.getenv("MAX_REQUEST_BODY_BYTES", "1000000"))


async def body_size_limit_middleware(request: Request, call_next):
    """Reject requests with Content-Length over the configured cap.

    Chunked transfer (no Content-Length header) is allowed — strict enforcement
    on chunked requests requires buffering, which defeats the purpose. Downstream
    Pydantic field caps (LongText 50K, BoundedDict 10K leaf strings) catch
    oversized fields after parse for that case.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            size = int(content_length)
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length header"}, status_code=400)
        if size > MAX_REQUEST_BODY_BYTES:
            logger.warning(
                "request body too large: size=%d max=%d path=%s",
                size,
                MAX_REQUEST_BODY_BYTES,
                request.url.path,
            )
            return JSONResponse(
                {
                    "detail": (
                        f"Request body too large: {size} bytes " f"(max {MAX_REQUEST_BODY_BYTES})"
                    )
                },
                status_code=413,
            )
    return await call_next(request)
