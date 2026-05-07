"""HTTPS enforcement + HSTS — Sprint 6.1 Phase 3a (Issue #7)."""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

HSTS_MAX_AGE = int(os.getenv("HSTS_MAX_AGE", "31536000"))
HSTS_HEADER = f"max-age={HSTS_MAX_AGE}; includeSubDomains"


def is_production() -> bool:
    """Strict equality, case-sensitive. Typos fail-safe to dev behavior.

    Same posture as Phase 2.2 / 2.3's "no kill switches" principle: a typo
    (`Production` capitalized, trailing space, etc.) gets dev behavior — never
    accidentally HTTPS-redirect on a developer's laptop.
    """
    return os.getenv("ENVIRONMENT", "development") == "production"


async def tls_enforcement_middleware(request: Request, call_next):
    """Redirect HTTP→HTTPS (308) on every PHI route; emit HSTS on HTTPS.

    Exempts /health* paths so LB probes pass through over plain HTTP from
    internal subnets without being redirected (LBs don't follow 308s by default
    and would mark the app unhealthy).
    """
    if request.url.path.startswith("/health"):
        return await call_next(request)

    if request.url.scheme != "https":
        url = request.url.replace(scheme="https")
        return RedirectResponse(url=str(url), status_code=308)
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = HSTS_HEADER
    return response


def install_tls_middleware_if_production(app: FastAPI) -> bool:
    """Install the TLS enforcement middleware on `app` iff ENVIRONMENT=production.

    Returns True if installed, False otherwise. Idempotent at module-load time
    (called once from app/main.py).
    """
    if not is_production():
        return False
    app.middleware("http")(tls_enforcement_middleware)
    return True


def maybe_warn_about_forwarded_allow_ips() -> None:
    """Log a WARNING if production is configured with FORWARDED_ALLOW_IPS=*.

    Visibility nudge: production deployments must run the container on a private
    network behind a TLS-terminating proxy. With * trust on any source, an
    internet-reachable container would let attackers spoof X-Forwarded-Proto.
    """
    if is_production() and os.getenv("FORWARDED_ALLOW_IPS", "*") == "*":
        logger.warning(
            "production with FORWARDED_ALLOW_IPS=*; container must not be "
            "internet-reachable directly. Trust X-Forwarded-Proto from any source."
        )
