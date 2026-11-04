"""#270: auth routes fail open on an audit outage, as ADR 0011 decision 1 says.

PHI routes stay fail-closed. Driven through the real app in-process, with a
real Redis client pointed at a closed port, so enqueue fails at the network.
"""

import pytest
import redis.asyncio as redis_async
from httpx import ASGITransport, AsyncClient

from app.database import init_db
from app.main import app
from app.security import audit_middleware as am
from app.security.auth import create_access_token
from app.security.rate_limit import limiter


@pytest.fixture
async def client_with_audit_down():
    await init_db()
    limiter.reset()
    unreachable = redis_async.from_url(
        "redis://127.0.0.1:1/0", socket_connect_timeout=0.5, socket_timeout=0.5
    )
    previous = am._audit_redis
    am.set_audit_redis(unreachable)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        am.set_audit_redis(previous)
        await unreachable.aclose()


@pytest.mark.asyncio
async def test_login_with_bad_credentials_still_gets_401(client_with_audit_down):
    response = await client_with_audit_down.post(
        "/auth/login",
        json={"email": "nobody@example.org", "password": "wrong"},  # pragma: allowlist secret
    )

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/auth/refresh", "/auth/logout"])
async def test_refresh_and_logout_with_a_bad_token_still_get_401(client_with_audit_down, route):
    response = await client_with_audit_down.post(
        route, headers={"Authorization": "Bearer not-a-jwt"}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_a_valid_token_still_issues_a_new_one(client_with_audit_down):
    token = create_access_token(
        {"sub": "researcher@example.org", "user_id": "USR-1", "role": "researcher"}
    )

    response = await client_with_audit_down.post(
        "/auth/refresh", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


@pytest.mark.asyncio
async def test_phi_route_still_fails_closed(client_with_audit_down):
    token = create_access_token(
        {"sub": "researcher@example.org", "user_id": "USR-1", "role": "researcher"}
    )

    response = await client_with_audit_down.get(
        "/research/", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_service_token_issuance_still_fails_closed(client_with_audit_down):
    # /a2a/token is audited but not on ADR 0011's fail-open list.
    response = await client_with_audit_down.post(
        "/a2a/token", json={"client_id": "x", "client_secret": "y"}  # pragma: allowlist secret
    )

    assert response.status_code == 503
