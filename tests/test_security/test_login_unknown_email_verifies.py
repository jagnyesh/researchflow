"""#285: an unknown email costs /auth/login a bcrypt verify, like a wrong password.

Login used to skip bcrypt when the email wasn't registered, so an unknown email
returned its 401 in about 2 ms and a registered one in about 190 ms. That gap
let anyone enumerate accounts. These tests count verifier calls rather than
timing them, because wall-clock assertions are flaky in CI.
"""

import uuid

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.api import auth as auth_api
from app.database import get_db_session, init_db
from app.database.models import User as UserModel
from app.main import app
from app.security import audit_middleware as am
from app.security.auth import get_password_hash, pwd_context
from app.security.rate_limit import limiter

PASSWORD = "a-test-password-for-285"  # pragma: allowlist secret
WRONG_PASSWORD = "not-the-password-for-285"  # pragma: allowlist secret


def _bcrypt_cost(hashed: str) -> str:
    # "$2b$12$<salt+digest>" -> "12"
    return hashed.split("$")[2]


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


@pytest.fixture
def verify_calls(monkeypatch):
    calls = []
    real_verify = auth_api.verify_password

    def spy(plain_password, hashed_password):
        calls.append(hashed_password)
        return real_verify(plain_password, hashed_password)

    monkeypatch.setattr(auth_api, "verify_password", spy)
    return calls


async def _seed_user() -> str:
    email = f"timing-{uuid.uuid4().hex[:8]}@example.org"
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
async def test_unknown_email_runs_a_bcrypt_verify_at_the_app_cost(client, verify_calls):
    unknown = f"nobody-{uuid.uuid4().hex[:8]}@example.org"

    response = await client.post("/auth/login", json={"email": unknown, "password": PASSWORD})

    assert response.status_code == 401
    assert len(verify_calls) == 1
    (dummy_hash,) = verify_calls
    assert pwd_context.identify(dummy_hash) == "bcrypt"
    assert _bcrypt_cost(dummy_hash) == _bcrypt_cost(get_password_hash(PASSWORD))


@pytest.mark.asyncio
async def test_unknown_email_and_wrong_password_get_the_same_401(client, verify_calls):
    email = await _seed_user()
    unknown = f"nobody-{uuid.uuid4().hex[:8]}@example.org"

    wrong_password = await client.post(
        "/auth/login", json={"email": email, "password": WRONG_PASSWORD}
    )
    unknown_email = await client.post(
        "/auth/login", json={"email": unknown, "password": WRONG_PASSWORD}
    )

    assert len(verify_calls) == 2
    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.json() == {"detail": "Incorrect email or password"}
        assert response.headers["www-authenticate"] == "Bearer"
