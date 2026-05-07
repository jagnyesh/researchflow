"""Tests for app/security/tls.py — Sprint 6.1 Phase 3a (Issue #7)."""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.security.tls import HSTS_HEADER, HSTS_MAX_AGE, is_production, tls_enforcement_middleware


@pytest.fixture
def app_with_tls():
    """Mini FastAPI app with the TLS middleware installed."""
    app = FastAPI()
    app.middleware("http")(tls_enforcement_middleware)

    @app.get("/sql_query")
    async def sql_query():
        return {"rows": []}

    @app.post("/sql_query")
    async def sql_query_post():
        return {"rows": []}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready():
        return {"status": "ready"}

    return app


# --- Cycle 1: tracer bullet ---


@pytest.mark.asyncio
async def test_http_request_redirects_to_https_with_308(app_with_tls):
    """The core promise of Phase 3a: HTTP requests to PHI routes redirect to HTTPS."""
    transport = ASGITransport(app=app_with_tls)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/sql_query", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"].startswith("https://")


@pytest.mark.asyncio
async def test_https_request_gets_hsts_header(app_with_tls):
    """HTTPS responses must include the Strict-Transport-Security header."""
    transport = ASGITransport(app=app_with_tls)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get("/sql_query")
    assert response.status_code == 200
    assert "strict-transport-security" in response.headers


@pytest.mark.asyncio
async def test_http_request_to_health_passes_through_no_redirect(app_with_tls):
    """LB health probes hit /health/* over plain HTTP from internal subnets;
    if we redirect them, the LB sees 308 and silently marks the app unhealthy.
    """
    transport = ASGITransport(app=app_with_tls)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response_health = await client.get("/health", follow_redirects=False)
        response_ready = await client.get("/health/ready", follow_redirects=False)
    assert response_health.status_code == 200
    assert response_ready.status_code == 200


@pytest.mark.asyncio
async def test_http_request_to_health_no_hsts_header(app_with_tls):
    """Health endpoints are entirely exempt — no HSTS either. Transport security
    for liveness probes is the deployment platform's concern, not the app's.
    """
    transport = ASGITransport(app=app_with_tls)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert "strict-transport-security" not in response.headers


@pytest.mark.asyncio
async def test_redirect_preserves_method_and_path(app_with_tls):
    """308 (not 301) keeps POST as POST after redirect — critical for write requests.

    Followed redirect should hit the POST handler (200), not get downgraded to GET
    (which would 405 since /sql_query supports both but the body would be lost).
    """
    transport = ASGITransport(app=app_with_tls)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/sql_query", json={"sql": "SELECT 1"}, follow_redirects=True)
    # If the redirect downgraded to GET, this would be 405 or hit the GET handler
    # (which returns the same shape but loses body). 200 + correct method preserved.
    assert response.status_code == 200
    assert response.json() == {"rows": []}


@pytest.mark.asyncio
async def test_http_request_with_x_forwarded_proto_https_passes_through(app_with_tls):
    """Production deployment scenario: LB terminates TLS, sends plain HTTP to the
    container with X-Forwarded-Proto: https. uvicorn (via --proxy-headers) rewrites
    request.url.scheme to "https" before the app sees the request. The TLS middleware
    then sees scheme=https and passes through.
    """
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    # Wrap the app with uvicorn's proxy-headers middleware to simulate the
    # --proxy-headers --forwarded-allow-ips * production config.
    wrapped = ProxyHeadersMiddleware(app_with_tls, trusted_hosts="*")
    transport = ASGITransport(app=wrapped)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/sql_query",
            headers={"X-Forwarded-Proto": "https"},
            follow_redirects=False,
        )
    assert response.status_code == 200
    assert response.json() == {"rows": []}
    # And HSTS should be on the response — proxy-headers correctly identified TLS
    assert "strict-transport-security" in response.headers


# --- ENVIRONMENT gate semantics ---


def test_is_production_returns_true_only_for_exact_match(monkeypatch):
    """Strict equality, case-sensitive. Typos fail-safe to dev behavior."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert is_production() is True


@pytest.mark.parametrize(
    "value", ["Production", "PRODUCTION", "prod", "production ", " production"]
)
def test_is_production_rejects_typos_and_variants(monkeypatch, value):
    """A capital P or trailing space gets dev behavior, not production. Fail-safe."""
    monkeypatch.setenv("ENVIRONMENT", value)
    assert is_production() is False


def test_is_production_default_is_false_when_unset(monkeypatch):
    """Unset env var → development → no HTTPS redirect on local make run."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert is_production() is False


# --- HSTS configuration locks ---


def test_hsts_max_age_is_one_year():
    """1 year (31536000s) — Chrome preload-list minimum + institutional defensible floor."""
    assert HSTS_MAX_AGE == 31536000


def test_includesubdomains_is_in_hsts_value():
    """Cascades to all current and future subdomains. Forecloses subdomain-on-HTTP footguns."""
    assert "includeSubDomains" in HSTS_HEADER


def test_preload_is_NOT_in_hsts_value():
    """Regression guard: preload submission hardcodes the domain into Chromium/Firefox/Safari
    source, removal is a months-long manual process, and the production domain is unknown.
    DO NOT add `preload` until that domain exists and is confirmed permanent.
    """
    assert "preload" not in HSTS_HEADER
