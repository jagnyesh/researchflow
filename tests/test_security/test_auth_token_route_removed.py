"""#284: /auth/token is removed, so /auth/login is the only password login.

The OAuth2 form route had no caller (Swagger's scheme is HTTPBearer) and
500'd on every call. A working copy would have been a second password-guessing
surface outside the audit middleware's auth allowlist.
"""

import uuid

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db_session, init_db
from app.database.models import User as UserModel
from app.main import app
from app.security import audit_middleware as am
from app.security.auth import create_access_token, get_password_hash
from app.security.rate_limit import limiter

PASSWORD = "a-test-password-for-284"  # pragma: allowlist secret


@pytest.fixture
async def client():
    await init_db()
    limiter.reset()
    audit_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(audit_redis)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        am.set_audit_redis(previous)
        await audit_redis.aclose()


async def _seed_user() -> str:
    email = f"token-{uuid.uuid4().hex[:8]}@example.org"
    async with get_db_session() as session:
        session.add(
            UserModel(
                id=f"USR-{uuid.uuid4().hex[:8].upper()}",
                email=email,
                hashed_password=get_password_hash(PASSWORD),
                full_name="Test User",
                role="researcher",
            )
        )
    return email


@pytest.mark.asyncio
async def test_credentials_that_log_in_get_no_token_from_auth_token(client):
    email = await _seed_user()
    # A bearer token gets the request past the audit middleware's auth check,
    # so a 404 here comes from routing, not from the middleware.
    bearer = create_access_token({"sub": email, "user_id": "USR-1", "role": "researcher"})

    login = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    token = await client.post(
        "/auth/token",
        data={"username": email, "password": PASSWORD},
        headers={"Authorization": f"Bearer {bearer}"},
    )

    assert login.status_code == 200
    assert token.status_code == 404
