"""PHI-safe RequestValidationError handler for the Phase 2.3 framework.

The default Pydantic 422 response includes the rejected `input` value. For PHI
or credential fields (email, password, sql, mrn, dob, initial_request), that's
PHI in the response body — which then ends up in any error monitoring system
(Sentry, Datadog) that ingests 422 responses.

This handler returns only `{loc, msg, type}` per error. Closes the leak vector
by construction.
"""

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def phi_safe_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Strip `input`, `url`, `ctx` from validation errors before responding.

    Logs at WARNING with loc + type only — never the input value.
    HTTP status stays 422 (FastAPI default; standard, expected by clients).
    """
    sanitized = []
    for err in exc.errors():
        loc = err.get("loc", [])
        type_ = err.get("type", "")
        sanitized.append(
            {
                "loc": list(loc),
                "msg": err.get("msg", ""),
                "type": type_,
            }
        )
        logger.warning("validation_failed loc=%s type=%s", loc, type_)
    return JSONResponse({"detail": sanitized}, status_code=422)
