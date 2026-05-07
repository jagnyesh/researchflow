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


# --- install_tls_middleware_if_production wiring helper ---


def test_install_returns_false_in_development(monkeypatch):
    """No middleware installed when ENVIRONMENT≠production."""
    from app.security.tls import install_tls_middleware_if_production

    monkeypatch.setenv("ENVIRONMENT", "development")
    app = FastAPI()
    assert install_tls_middleware_if_production(app) is False


def test_install_wires_middleware_when_production(monkeypatch):
    """Returns True and the middleware is actually on app.user_middleware."""
    from app.security.tls import install_tls_middleware_if_production

    monkeypatch.setenv("ENVIRONMENT", "production")
    app = FastAPI()
    assert install_tls_middleware_if_production(app) is True

    # Verify the middleware is actually wired (FastAPI stores it in user_middleware)
    middleware_funcs = []
    for mw in app.user_middleware:
        kwargs = getattr(mw, "kwargs", {}) or {}
        dispatch = kwargs.get("dispatch")
        if dispatch is not None:
            middleware_funcs.append(dispatch)
    assert tls_enforcement_middleware in middleware_funcs


# --- FORWARDED_ALLOW_IPS=* startup warning ---


def test_warning_logged_when_production_with_wildcard_forwarded_allow_ips(monkeypatch, caplog):
    """Production + FORWARDED_ALLOW_IPS=* logs a warning — container must not be
    internet-reachable directly. Visibility nudge without forcing operator action.
    """
    import logging
    from app.security.tls import maybe_warn_about_forwarded_allow_ips

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    with caplog.at_level(logging.WARNING):
        maybe_warn_about_forwarded_allow_ips()
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "FORWARDED_ALLOW_IPS=*" in log_text
    assert "internet-reachable" in log_text


def test_warning_not_logged_in_development(monkeypatch, caplog):
    """Dev or staging environments don't warn — they're expected to use *."""
    import logging
    from app.security.tls import maybe_warn_about_forwarded_allow_ips

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    with caplog.at_level(logging.WARNING):
        maybe_warn_about_forwarded_allow_ips()
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "FORWARDED_ALLOW_IPS" not in log_text


def test_warning_not_logged_when_forwarded_allow_ips_is_specific_cidr(monkeypatch, caplog):
    """Operator hardened FORWARDED_ALLOW_IPS to a specific subnet — no warning."""
    import logging
    from app.security.tls import maybe_warn_about_forwarded_allow_ips

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.0/8")
    with caplog.at_level(logging.WARNING):
        maybe_warn_about_forwarded_allow_ips()
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "FORWARDED_ALLOW_IPS" not in log_text


# --- Wiring integration: real app.main:app ---


def test_tls_middleware_NOT_on_real_app_in_dev_mode():
    """Default test environment has ENVIRONMENT unset → development → TLS middleware
    NOT installed on app.main:app. This guards against a regression where someone
    flips the conditional and breaks every existing test (every endpoint suddenly
    redirects to HTTPS in test mode).
    """
    from app.main import app

    middleware_funcs = []
    for mw in app.user_middleware:
        kwargs = getattr(mw, "kwargs", {}) or {}
        dispatch = kwargs.get("dispatch")
        if dispatch is not None:
            middleware_funcs.append(dispatch)
    assert (
        tls_enforcement_middleware not in middleware_funcs
    ), "TLS middleware is on app.main:app in dev mode — would break every endpoint test"


# --- TrustedHostMiddleware (CSO Finding 1 fix — open redirect via Host header) ---


def test_install_trusted_host_returns_false_in_development(monkeypatch):
    """Dev mode: don't install TrustedHostMiddleware (developers use localhost, etc.)."""
    from app.security.tls import install_trusted_host_middleware_if_production

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ALLOWED_HOSTS", "app.example.com")
    app = FastAPI()
    assert install_trusted_host_middleware_if_production(app) is False


def test_install_trusted_host_returns_false_when_allowed_hosts_is_wildcard(monkeypatch):
    """Production with ALLOWED_HOSTS=* explicitly opts out of host validation.
    Combined with the startup warning, this is the documented escape hatch for
    deployments that haven't set the canonical hostname yet.
    """
    from app.security.tls import install_trusted_host_middleware_if_production

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    app = FastAPI()
    assert install_trusted_host_middleware_if_production(app) is False


def test_install_trusted_host_returns_true_when_production_with_explicit_hosts(monkeypatch):
    """Production with a real ALLOWED_HOSTS value installs the middleware."""
    from app.security.tls import install_trusted_host_middleware_if_production

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_HOSTS", "app.example.com,api.example.com")
    app = FastAPI()
    assert install_trusted_host_middleware_if_production(app) is True


@pytest.mark.asyncio
async def test_attacker_host_header_is_rejected_with_400():
    """CSO Finding 1: regression guard against open redirect via attacker-controlled Host.

    Install order (mirroring production): TLS first (added 1st → runs 2nd),
    TrustedHost LAST (added 2nd → runs 1st). Host validation gates BEFORE the
    redirect logic — attacker host gets 400, never sees a 308 to evil.com.
    """
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app = FastAPI()
    # Order matters: FastAPI runs middleware in reverse-registration order.
    app.middleware("http")(tls_enforcement_middleware)  # added 1st → runs 2nd
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["app.example.com"]
    )  # added 2nd → runs 1st

    @app.get("/")
    async def root():
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://app.example.com") as client:
        # Forge Host header to simulate attacker
        response = await client.get(
            "/", headers={"Host": "evil-attacker.example"}, follow_redirects=False
        )
    assert response.status_code == 400, (
        f"Attacker host not rejected — open redirect vector. Got {response.status_code}: "
        f"location={response.headers.get('location', 'N/A')}"
    )


@pytest.mark.asyncio
async def test_legitimate_host_is_accepted_after_redirect():
    """Sanity check: real hostname still gets the 308 + HSTS treatment."""
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app = FastAPI()
    app.middleware("http")(tls_enforcement_middleware)  # added 1st → runs 2nd
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["app.example.com"]
    )  # added 2nd → runs 1st

    @app.get("/")
    async def root():
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://app.example.com") as client:
        response = await client.get("/", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"].startswith("https://app.example.com")


def test_warning_logged_when_production_with_wildcard_allowed_hosts(monkeypatch, caplog):
    """Same posture as FORWARDED_ALLOW_IPS warning — visibility nudge to the operator."""
    import logging
    from app.security.tls import maybe_warn_about_allowed_hosts

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    with caplog.at_level(logging.WARNING):
        maybe_warn_about_allowed_hosts()
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "ALLOWED_HOSTS=*" in log_text
    assert "open redirect" in log_text.lower()


def test_allowed_hosts_warning_not_logged_when_set(monkeypatch, caplog):
    """Operator hardened ALLOWED_HOSTS to a real hostname — no warning."""
    import logging
    from app.security.tls import maybe_warn_about_allowed_hosts

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_HOSTS", "app.example.com")
    with caplog.at_level(logging.WARNING):
        maybe_warn_about_allowed_hosts()
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "ALLOWED_HOSTS" not in log_text
