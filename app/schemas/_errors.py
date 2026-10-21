"""PHI-safe RequestValidationError handler for the Phase 2.3 framework.

The default Pydantic 422 response includes the rejected `input` value. For PHI
or credential fields (email, password, sql, mrn, dob, initial_request), that's
PHI in the response body — which then ends up in any error monitoring system
(Sentry, Datadog) that ingests 422 responses.

This handler returns only `{loc, msg, type}` per error. Closes the leak vector
by construction.
"""

import logging
import traceback
import uuid

from fastapi import HTTPException, Request
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


def _exception_type_chain(exc: BaseException) -> str:
    """Type names only — `exc`, its cause/context chain, and SQLAlchemy's `.orig`.
    Never a message: driver and StatementError strings embed row values and
    bound parameters (#175)."""
    names, seen, node = [], set(), exc
    while node is not None and id(node) not in seen and len(names) < 6:
        seen.add(id(node))
        names.append(type(node).__name__)
        orig = getattr(node, "orig", None)
        if isinstance(orig, BaseException) and id(orig) not in seen:
            seen.add(id(orig))
            names.append(type(orig).__name__)
        node = node.__cause__ or node.__context__
    return " <- ".join(names)


def log_internal_error(
    log: logging.Logger, context: str, exc: BaseException, level: int = logging.ERROR
) -> str:
    """Log an unexpected exception PHI-safely and return its correlation ref.

    The line carries `context`, the ref, the exception type chain, and the
    traceback frames (code locations, not runtime values) — enough to find
    the failure without the message text (ADR 0029).
    """
    ref = uuid.uuid4().hex[:12]
    frames = "".join(traceback.format_tb(exc.__traceback__))
    # Contexts interpolate path params; escape line breaks so one can't forge log lines.
    safe_context = context.replace("\r", "\\r").replace("\n", "\\n")
    log.log(
        level, "%s ref=%s exc_types=%s\n%s", safe_context, ref, _exception_type_chain(exc), frames
    )
    return ref


def internal_error(log: logging.Logger, context: str, exc: BaseException) -> HTTPException:
    """The 500 to raise from an API `except Exception` block (#175).

    Kept as a per-site HTTPException rather than a global Exception handler:
    Starlette runs those outside the audit middleware, which would drop
    PHI_ACCESS_COMPLETED for every 500 (ADR 0029).
    """
    ref = log_internal_error(log, context, exc)
    return HTTPException(status_code=500, detail=f"Internal server error (ref: {ref})")
