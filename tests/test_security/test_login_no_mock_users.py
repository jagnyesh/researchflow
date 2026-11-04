"""#280: /auth/login only accepts users from the users table.

The hardcoded MOCK_USERS fallback (incl. an admin, password "password123")
let any deployment accept a known admin credential.
"""

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import auth as auth_api
from app.database import get_db_session, init_db
from app.database.models import User as UserModel
from app.security.auth import get_password_hash
from app.security.rate_limit import limiter, setup_rate_limiting

PASSWORD = "a-test-password-for-280"  # pragma: allowlist secret


@pytest.fixture
async def client():
    await init_db()
    limiter.reset()
    app = FastAPI()
    setup_rate_limiting(app)
    app.include_router(auth_api.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _seed_user(role: str) -> str:
    email = f"{role}-{uuid.uuid4().hex[:8]}@example.org"
    async with get_db_session() as session:
        session.add(
            UserModel(
                id=f"USR-{uuid.uuid4().hex[:8].upper()}",
                email=email,
                hashed_password=get_password_hash(PASSWORD),
                full_name="Test User",
                role=role,
            )
        )
    return email


@pytest.mark.asyncio
@pytest.mark.parametrize("email", ["admin@example.com", "researcher@example.com"])
async def test_former_mock_credentials_are_rejected(client, email):
    response = await client.post(
        "/auth/login", json={"email": email, "password": "password123"}  # pragma: allowlist secret
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_seeded_user_logs_in_with_their_role(client):
    email = await _seed_user("admin")

    response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"


@pytest.mark.asyncio
async def test_seeded_user_with_wrong_password_is_rejected(client):
    email = await _seed_user("researcher")

    response = await client.post(
        "/auth/login",
        json={"email": email, "password": "wrong-password"},  # pragma: allowlist secret
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_bootstrap_script_creates_a_user_who_can_log_in(client):
    # Replaces the mock admin as the way to get a first admin (POST /users needs one).
    from scripts.create_user import create_user

    email = f"bootstrap-{uuid.uuid4().hex[:8]}@example.org"
    await create_user(email=email, password=PASSWORD, role="admin", full_name="First Admin")

    response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"


@pytest.mark.asyncio
async def test_bootstrap_script_normalizes_email_like_login_does(client):
    from scripts.create_user import create_user

    local = f"Boot-{uuid.uuid4().hex[:8]}"
    await create_user(
        email=f"{local}@EXAMPLE.ORG", password=PASSWORD, role="admin", full_name="First Admin"
    )

    response = await client.post(
        "/auth/login", json={"email": f"{local}@EXAMPLE.ORG", "password": PASSWORD}
    )

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "email,password",
    [("not-an-email", PASSWORD), ("ok@example.org", "x" * 201)],
)
async def test_bootstrap_script_rejects_what_login_would_reject(email, password):
    from scripts.create_user import create_user

    with pytest.raises(ValueError):
        await create_user(email=email, password=password, role="admin", full_name="First Admin")
