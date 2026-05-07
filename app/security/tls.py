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


def install_trusted_host_middleware_if_production(app: FastAPI) -> bool:
    """Install Starlette's TrustedHostMiddleware to validate Host header in production.

    Closes CSO Finding 1: without Host validation, an attacker-controlled Host header
    causes our 308 redirect to point at attacker.com (open redirect → phishing).

    Returns True if installed. Skips installation when ENVIRONMENT≠production OR
    when ALLOWED_HOSTS=* (explicit wildcard escape hatch + startup warning).
    """
    if not is_production():
        return False
    raw = os.getenv("ALLOWED_HOSTS", "*")
    allowed = [h.strip() for h in raw.split(",") if h.strip()]
    if allowed == ["*"]:
        return False  # explicit opt-out; warning nudges operator to set hosts
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed)
    return True


def maybe_warn_about_allowed_hosts() -> None:
    """Log a WARNING if production is configured with ALLOWED_HOSTS=*.

    Without Host validation, the 308 redirect honors any Host header the client
    sends — an open redirect vector that defeats the transport-security narrative.
    """
    if is_production() and os.getenv("ALLOWED_HOSTS", "*") == "*":
        logger.warning(
            "production with ALLOWED_HOSTS=*; Host header not validated. "
            "Set ALLOWED_HOSTS=app.example.com to defend against open redirect."
        )
