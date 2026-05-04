"""Integration test for the Phase 2.3 validation framework end-to-end (Issue #6).

Hits a real PHI endpoint with a malformed body and asserts:
- 422 response with the Q4 PHI-safe contract (only loc/msg/type)
- Audit middleware emitted both PHI_ACCESS_REQUESTED AND PHI_ACCESS_COMPLETED
  with status_code=422 — verifies Phase 2.2's "no separate VALIDATION_FAILURE
  event needed" claim.
"""

import json
import os
from datetime import timedelta

import fakeredis.aioredis
import pytest

# Ensure orchestrator is disabled so app boot is light.
os.environ.setdefault("ENABLE_ORCHESTRATOR", "false")


@pytest.fixture
async def fake_audit_redis():
    """Replicates the Phase 2.2 fakeredis fixture pattern."""
    from app.security import audit_middleware as am

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(client)
    yield client
    am.set_audit_redis(previous)
    await client.aclose()


@pytest.mark.asyncio
async def test_phi_route_with_invalid_body_returns_phi_safe_422_and_full_audit_pair(
    fake_audit_redis,
):
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.security.auth import create_access_token
    from app.security import audit_middleware as am

    token = create_access_token(
        {"sub": "qa@example.com", "user_id": "qa-1", "role": "researcher"},
        expires_delta=timedelta(minutes=5),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # POST /research/submit with researcher_email malformed AND a leaked PHI marker
        response = await client.post(
            "/research/submit",
            json={
                "researcher_name": "Dr. Test",
                "researcher_email": "DEFINITELY-NOT-AN-EMAIL-PHI-MARKER",
                "irb_number": "IRB-2024-001",
                "initial_request": "find patients",
            },
            headers={"authorization": f"Bearer {token}"},
        )

    # --- assert 422 + PHI-safe response shape ---
    assert response.status_code == 422
    body_text = response.text
    assert "DEFINITELY-NOT-AN-EMAIL-PHI-MARKER" not in body_text
    assert "errors.pydantic.dev" not in body_text

    body = response.json()
    for err in body["detail"]:
        assert set(err.keys()) <= {"loc", "msg", "type"}

    # --- assert audit pair was emitted (verifies Phase 2.2 design claim) ---
    events = []
    while True:
        item = await fake_audit_redis.lpop(am.AUDIT_QUEUE_KEY)
        if item is None:
            break
        events.append(json.loads(item))

    types_seen = {e["event_type"] for e in events}
    assert "PHI_ACCESS_REQUESTED" in types_seen, f"missing pre-event in audit queue: {types_seen}"
    assert "PHI_ACCESS_COMPLETED" in types_seen, f"missing post-event in audit queue: {types_seen}"

    completed = next(e for e in events if e["event_type"] == "PHI_ACCESS_COMPLETED")
    assert completed["status_code"] == 422


@pytest.mark.asyncio
async def test_oversized_body_rejected_413_without_polluting_audit_queue(fake_audit_redis):
    """CSO Finding 1 fix: oversized requests get 413 BEFORE audit middleware runs.

    Verifies the body_size_limit_middleware is wired in front of audit_middleware,
    so attacker probing with 100MB bodies doesn't fill the audit queue with noise.
    """
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.security import audit_middleware as am
    from app.security.body_size import MAX_REQUEST_BODY_BYTES

    transport = ASGITransport(app=app)
    huge_body = '{"sql": "' + ("x" * (MAX_REQUEST_BODY_BYTES + 100)) + '"}'

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/sql_query",
            content=huge_body,
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413

    # Audit queue MUST be empty — body_size middleware short-circuited before audit ran
    queue_len = await fake_audit_redis.llen(am.AUDIT_QUEUE_KEY)
    assert (
        queue_len == 0
    ), f"audit queue had {queue_len} events; body-size middleware order is wrong"
