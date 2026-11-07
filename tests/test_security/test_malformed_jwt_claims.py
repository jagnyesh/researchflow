"""#227: a signed token with a malformed claim set is an invalid token.

An integer user_id made TokenData raise a pydantic ValidationError that
escaped the audit middleware: a plain 500, no audit event, and the claim
value in the server log. Driven through the real app; the audit queue is
fakeredis, as in the other audit middleware tests. The leak site was the
server's (uvicorn) error log, which this in-process harness doesn't run, so
these tests pin the status, the audit event and the response body.
"""

import json

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import init_db
from app.main import app
from app.security import audit_middleware as am
from app.security.auth import create_access_token
from app.security.rate_limit import limiter

NEEDLE = 918273645  # the malformed claim value; must never reach the response


@pytest.fixture
async def client_and_queue():
    await init_db()
    limiter.reset()
    queue = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(queue)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, queue
    finally:
        am.set_audit_redis(previous)
        await queue.aclose()


def _token(**claims):
    return create_access_token({"sub": "researcher@example.test", "role": "researcher", **claims})


async def _events(queue):
    events = []
    while (item := await queue.lpop(am.AUDIT_QUEUE_KEY)) is not None:
        events.append(json.loads(item))
    return events


MALFORMED = [
    {"user_id": NEEDLE},
    {"user_id": "u-1", "role": [NEEDLE]},
    {},  # no user_id claim
    {"user_id": None},
    {"user_id": ""},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("claims", MALFORMED)
async def test_a_malformed_token_on_a_phi_route_is_an_audited_401(client_and_queue, claims):
    client, queue = client_and_queue

    response = await client.get(
        "/research/", headers={"Authorization": f"Bearer {_token(**claims)}"}
    )

    assert response.status_code == 401
    assert [e["event_type"] for e in await _events(queue)] == ["UNAUTH_PHI_ATTEMPT"]
    assert str(NEEDLE) not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/auth/refresh", "/auth/logout"])
@pytest.mark.parametrize("claims", MALFORMED)
async def test_a_malformed_token_on_a_user_dependency_route_is_401(client_and_queue, claims, route):
    client, _ = client_and_queue

    response = await client.post(route, headers={"Authorization": f"Bearer {_token(**claims)}"})

    assert response.status_code == 401
    assert str(NEEDLE) not in response.text


@pytest.mark.asyncio
async def test_a_well_formed_token_still_refreshes(client_and_queue):
    client, _ = client_and_queue

    response = await client.post(
        "/auth/refresh", headers={"Authorization": f"Bearer {_token(user_id='u-1')}"}
    )

    assert response.status_code == 200
