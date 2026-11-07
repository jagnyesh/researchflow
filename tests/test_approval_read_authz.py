"""#289: approval reads follow the #282 research-request visibility rule.

Real JWTs through the real auth dependency, real (test) database; no
dependency overrides or mocked sessions.
"""

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import approvals
from app.database import Approval, ResearchRequest, get_db_session, init_db
from app.security.auth import create_access_token


def _token(email: str, role: str) -> dict:
    token = create_access_token({"sub": email, "user_id": f"USR-{role}", "role": role})
    return {"Authorization": f"Bearer {token}"}


async def _seed(owner_email: str) -> tuple[str, int]:
    request_id = f"REQ-TEST-{uuid.uuid4().hex[:8].upper()}"
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="Synthetic Researcher",
                researcher_email=owner_email,
                initial_request="synthetic request text",
                current_state="phenotype_review",
            )
        )
        await session.flush()
        approval = Approval(
            request_id=request_id,
            approval_type="phenotype_sql",
            submitted_by="phenotype_agent",
            approval_data={"sql_query": f"SELECT 1 -- {request_id}"},
            status="pending",
        )
        session.add(approval)
        await session.flush()
        approval_id = approval.id
    return request_id, approval_id


@pytest.fixture
async def setup():
    await init_db()
    alice = f"alice-{uuid.uuid4().hex[:6]}@example.org"
    bob = f"bob-{uuid.uuid4().hex[:6]}@example.org"
    seeded = {alice: await _seed(alice), bob: await _seed(bob)}

    app = FastAPI()
    app.include_router(approvals.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, alice, bob, seeded


def _pending_request_ids(response) -> set:
    return {a["request_id"] for a in response.json()["approvals"]}


@pytest.mark.asyncio
async def test_researcher_cannot_read_another_researchers_approval_by_id(setup):
    client, alice, bob, seeded = setup

    other = await client.get(f"/approvals/{seeded[bob][1]}", headers=_token(alice, "researcher"))
    own = await client.get(f"/approvals/{seeded[alice][1]}", headers=_token(alice, "researcher"))

    assert other.status_code == 404
    assert own.status_code == 200
    assert own.json()["approval_data"]["sql_query"].endswith(seeded[alice][0])


@pytest.mark.asyncio
async def test_researcher_cannot_list_another_researchers_request_approvals(setup):
    client, alice, bob, seeded = setup

    other = await client.get(
        f"/approvals/request/{seeded[bob][0]}", headers=_token(alice, "researcher")
    )
    own = await client.get(
        f"/approvals/request/{seeded[alice][0]}", headers=_token(alice, "researcher")
    )

    assert other.status_code == 404
    assert own.status_code == 200
    assert [a["id"] for a in own.json()["approvals"]] == [seeded[alice][1]]


@pytest.mark.asyncio
async def test_pending_queue_shows_a_researcher_only_their_own_approvals(setup):
    client, alice, bob, seeded = setup

    response = await client.get("/approvals/pending", headers=_token(alice, "researcher"))

    assert response.status_code == 200
    ids = _pending_request_ids(response)
    assert seeded[alice][0] in ids
    assert seeded[bob][0] not in ids


@pytest.mark.asyncio
@pytest.mark.parametrize("spoofed", ["admin", "data_steward", "informatician"])
async def test_user_role_query_param_does_not_widen_the_pending_queue(setup, spoofed):
    client, alice, bob, seeded = setup

    response = await client.get(
        "/approvals/pending", params={"user_role": spoofed}, headers=_token(alice, "researcher")
    )

    assert seeded[bob][0] not in _pending_request_ids(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "data_steward"])
async def test_staff_roles_read_every_approval(setup, role):
    client, alice, bob, seeded = setup
    headers = _token(f"staff-{role}@example.org", role)

    by_id = await client.get(f"/approvals/{seeded[bob][1]}", headers=headers)
    by_request = await client.get(f"/approvals/request/{seeded[bob][0]}", headers=headers)
    pending = await client.get("/approvals/pending", headers=headers)

    assert by_id.status_code == 200
    assert [a["id"] for a in by_request.json()["approvals"]] == [seeded[bob][1]]
    assert {seeded[alice][0], seeded[bob][0]} <= _pending_request_ids(pending)


@pytest.mark.asyncio
async def test_unknown_role_is_treated_as_owner_only(setup):
    client, alice, bob, seeded = setup
    headers = _token("someone@example.org", "informatician")

    by_id = await client.get(f"/approvals/{seeded[bob][1]}", headers=headers)
    by_request = await client.get(f"/approvals/request/{seeded[bob][0]}", headers=headers)
    pending = await client.get("/approvals/pending", headers=headers)

    assert by_id.status_code == 404
    assert by_request.status_code == 404
    assert seeded[bob][0] not in _pending_request_ids(pending)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/approvals/pending", "/approvals/1", "/approvals/request/X"])
async def test_unauthenticated_caller_is_rejected(setup, path):
    client, *_ = setup

    response = await client.get(path)

    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_owner_match_ignores_email_case(setup):
    client, *_ = setup
    owner = f"Carol-{uuid.uuid4().hex[:6]}@Example.ORG"
    request_id, approval_id = await _seed(owner)
    headers = _token(owner.lower(), "researcher")

    by_id = await client.get(f"/approvals/{approval_id}", headers=headers)
    by_request = await client.get(f"/approvals/request/{request_id}", headers=headers)
    pending = await client.get("/approvals/pending", headers=headers)

    assert by_id.status_code == 200
    assert by_request.status_code == 200
    assert request_id in _pending_request_ids(pending)


@pytest.mark.asyncio
async def test_approval_without_a_request_is_staff_only(setup):
    client, alice, *_ = setup
    async with get_db_session() as session:
        orphan = Approval(
            request_id=None,
            approval_type="phenotype_sql",
            submitted_by="phenotype_agent",
            approval_data={"sql_query": "SELECT 1"},
            status="pending",
        )
        session.add(orphan)
        await session.flush()
        orphan_id = orphan.id

    researcher = await client.get(f"/approvals/{orphan_id}", headers=_token(alice, "researcher"))
    admin = await client.get(
        f"/approvals/{orphan_id}", headers=_token("staff@example.org", "admin")
    )

    assert researcher.status_code == 404
    assert admin.status_code == 200


@pytest.mark.asyncio
async def test_token_without_a_role_claim_is_owner_only(setup):
    client, alice, bob, seeded = setup
    token = create_access_token({"sub": alice, "user_id": "USR-norole"})
    headers = {"Authorization": f"Bearer {token}"}

    other = await client.get(f"/approvals/{seeded[bob][1]}", headers=headers)
    own = await client.get(f"/approvals/{seeded[alice][1]}", headers=headers)

    assert other.status_code == 404
    assert own.status_code == 200
