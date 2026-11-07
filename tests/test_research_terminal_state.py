"""#53: "complete" is the only delivered state.

LangGraph never writes "delivered" (data_delivery -> complete); that term in
research.py's terminal-state checks only matched A2A-era rows. Decided
2026-11-04: drop it (option A); such rows read as not delivered. Real JWTs,
real auth dependency, real test DB.
"""

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import research
from app.database import ResearchRequest, get_db_session, init_db
from app.database.models import DataDelivery
from app.security.auth import create_access_token

OWNER = "owner-53@example.org"


def _auth():
    token = create_access_token({"sub": OWNER, "user_id": "USR-53", "role": "researcher"})
    return {"Authorization": f"Bearer {token}"}


async def _seed(state):
    request_id = f"REQ-53-{uuid.uuid4().hex[:8].upper()}"
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="Synthetic Researcher",
                researcher_email=OWNER,
                initial_request="synthetic request text",
                current_state=state,
            )
        )
        session.add(DataDelivery(request_id=request_id, delivery_format="CSV", cohort_size=3))
    return request_id


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DELIVERY_PATH", str(tmp_path))
    await init_db()
    app = FastAPI()
    app.include_router(research.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_a_complete_request_reads_as_delivered(client):
    request_id = await _seed("complete")

    response = await client.get(f"/research/{request_id}/delivery", headers=_auth())

    assert response.status_code == 200
    assert response.json()["delivered"] is True


@pytest.mark.asyncio
async def test_a_legacy_delivered_state_no_longer_counts_as_delivered(client):
    request_id = await _seed("delivered")

    info = await client.get(f"/research/{request_id}/delivery", headers=_auth())
    package = await client.get(f"/research/{request_id}/download", headers=_auth())
    one_file = await client.get(f"/research/{request_id}/download/data.csv", headers=_auth())

    assert info.json()["delivered"] is False
    assert package.status_code == 400
    assert one_file.status_code == 400
