"""Integration test: PHI-safe validation handler is installed on app.main:app.

Phase 2.3 Issue #4 commit 2 wires the handler into the FastAPI app via
app.add_exception_handler in lifespan. This test guards against regressions
where the handler gets removed or replaced with the default Pydantic one.
"""

import os

import pytest

# Lifespan-side: don't boot the orchestrator (heavy + needs API key).
os.environ.setdefault("ENABLE_ORCHESTRATOR", "false")


@pytest.mark.asyncio
async def test_phi_safe_handler_is_installed_on_real_app():
    from fastapi.exceptions import RequestValidationError
    from app.main import app
    from app.schemas._errors import phi_safe_validation_handler

    handler = app.exception_handlers.get(RequestValidationError)
    assert (
        handler is phi_safe_validation_handler
    ), f"expected phi_safe_validation_handler, got {handler!r}"


@pytest.mark.asyncio
async def test_real_app_422_response_strips_input(fake_audit_redis):
    """Hit a real PHI route with a malformed body; assert PHI-safe 422."""
    from datetime import timedelta
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.security.auth import create_access_token

    token = create_access_token(
        {"sub": "qa@example.com", "user_id": "qa-1", "role": "researcher"},
        expires_delta=timedelta(minutes=5),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # /sql_query expects {sql: str}; send wrong shape with a "secret" value
        response = await client.post(
            "/sql_query",
            json={"sql": 123, "leaked_value": "PHI-marker-that-must-not-leak"},
            headers={"authorization": f"Bearer {token}"},
        )

    assert response.status_code == 422
    body_text = response.text
    assert "PHI-marker-that-must-not-leak" not in body_text
    assert "errors.pydantic.dev" not in body_text
    body = response.json()
    for err in body["detail"]:
        assert set(err.keys()) <= {"loc", "msg", "type"}


@pytest.fixture
async def fake_audit_redis():
    """Reuse the audit-pipeline fakeredis fixture pattern from Phase 2.2."""
    import fakeredis.aioredis
    from app.security import audit_middleware as am

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(client)
    yield client
    am.set_audit_redis(previous)
    await client.aclose()
