"""#282: a researcher sees only their own research requests.

Real JWTs through the real auth dependency, real (test) database; no
dependency overrides or mocked sessions.
"""

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import research
from app.database import ResearchRequest, get_db_session, init_db
from app.security.auth import create_access_token


def _token(email: str, role: str) -> dict:
    token = create_access_token({"sub": email, "user_id": f"USR-{role}", "role": role})
    return {"Authorization": f"Bearer {token}"}


async def _seed_request(owner_email: str) -> str:
    request_id = f"REQ-TEST-{uuid.uuid4().hex[:8].upper()}"
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="Synthetic Researcher",
                researcher_email=owner_email,
                initial_request="synthetic request text",
                current_state="new_request",
            )
        )
    return request_id


@pytest.fixture
async def setup():
    await init_db()
    alice = f"alice-{uuid.uuid4().hex[:6]}@example.org"
    bob = f"bob-{uuid.uuid4().hex[:6]}@example.org"
    requests = {alice: await _seed_request(alice), bob: await _seed_request(bob)}

    app = FastAPI()
    app.include_router(research.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, alice, bob, requests


@pytest.mark.asyncio
async def test_researcher_cannot_read_another_researchers_request(setup):
    client, alice, bob, requests = setup

    other = await client.get(f"/research/{requests[bob]}", headers=_token(alice, "researcher"))
    own = await client.get(f"/research/{requests[alice]}", headers=_token(alice, "researcher"))

    assert other.status_code == 404
    assert own.status_code == 200


@pytest.mark.asyncio
async def test_listing_shows_a_researcher_only_their_own_requests(setup):
    client, alice, bob, requests = setup

    response = await client.get("/research/", headers=_token(alice, "researcher"))

    ids = {r["request_id"] for r in response.json()["requests"]}
    assert requests[alice] in ids
    assert requests[bob] not in ids


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "data_steward"])
async def test_staff_roles_keep_access_to_every_request(setup, role):
    client, alice, bob, requests = setup

    response = await client.get(
        f"/research/{requests[bob]}", headers=_token(f"staff-{role}@example.org", role)
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_unknown_role_is_treated_as_owner_only(setup):
    client, alice, bob, requests = setup

    response = await client.get(
        f"/research/{requests[bob]}", headers=_token("someone@example.org", "informatician")
    )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["{id}/delivery", "{id}/download", "{id}/download/cohort.csv"])
async def test_delivery_routes_hide_another_researchers_request(setup, path):
    client, alice, bob, requests = setup

    response = await client.get(
        "/research/" + path.format(id=requests[bob]), headers=_token(alice, "researcher")
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_caller_is_rejected(setup):
    client, alice, bob, requests = setup

    response = await client.get(f"/research/{requests[alice]}")

    assert response.status_code in (401, 403)
