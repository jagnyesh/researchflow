"""Tests for app/schemas/_errors.py — Phase 2.3 PHI-safe validation handler (Issue #4)."""

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import AsyncClient, ASGITransport

from app.schemas._base import PHIInputModel
from app.schemas._errors import phi_safe_validation_handler
from app.schemas._types import EmailStr, ShortText, IRBNumber


@pytest.fixture
def app_with_handler():
    """Mini FastAPI app exercising the handler against a strict schema."""

    class _Body(PHIInputModel):
        email: EmailStr
        name: ShortText
        irb: IRBNumber

    app = FastAPI()
    app.add_exception_handler(RequestValidationError, phi_safe_validation_handler)

    @app.post("/test")
    async def endpoint(body: _Body):
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_response_status_is_422(app_with_handler):
    transport = ASGITransport(app=app_with_handler)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/test", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_response_has_only_loc_msg_type(app_with_handler):
    transport = ASGITransport(app=app_with_handler)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/test", json={})
    body = response.json()
    assert "detail" in body
    assert isinstance(body["detail"], list)
    assert len(body["detail"]) >= 1
    for err in body["detail"]:
        assert set(err.keys()) == {
            "loc",
            "msg",
            "type",
        }, f"unexpected keys in error: {set(err.keys()) - {'loc', 'msg', 'type'}}"


@pytest.mark.asyncio
async def test_response_does_not_leak_input_value(app_with_handler):
    """The rejected value must NOT appear in the response — PHI leak vector."""
    secret_email = "leaked-secret-email@phi.example.com"
    transport = ASGITransport(app=app_with_handler)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/test",
            json={"email": secret_email, "name": "alice", "irb": "garbage"},
        )
    body_text = response.text
    assert secret_email not in body_text, "leaked input value into 422 response"
    assert "garbage" not in body_text, "leaked rejected IRB value into 422 response"


@pytest.mark.asyncio
async def test_response_does_not_leak_pydantic_url(app_with_handler):
    """The Pydantic docs URL would leak Pydantic version. Strip it."""
    transport = ASGITransport(app=app_with_handler)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/test", json={})
    body_text = response.text
    assert "errors.pydantic.dev" not in body_text


@pytest.mark.asyncio
async def test_response_does_not_leak_ctx(app_with_handler):
    """`ctx` can contain field-specific info (some Pydantic types put input in ctx.input)."""
    transport = ASGITransport(app=app_with_handler)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/test",
            json={"email": "a@b.co", "name": "x" * 201, "irb": "IRB-001"},
        )
    body = response.json()
    for err in body["detail"]:
        assert "ctx" not in err
        assert "input" not in err
        assert "url" not in err


@pytest.mark.asyncio
async def test_extra_fields_get_phi_safe_422(app_with_handler):
    """PHIInputModel rejects unknown fields; verify that 422 also passes through the handler cleanly."""
    transport = ASGITransport(app=app_with_handler)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/test",
            json={"email": "a@b.co", "name": "alice", "irb": "IRB-001", "is_admin": True},
        )
    assert response.status_code == 422
    body = response.json()
    extra_errors = [e for e in body["detail"] if e["type"] == "extra_forbidden"]
    assert len(extra_errors) == 1
    assert extra_errors[0]["loc"] == ["body", "is_admin"]


@pytest.mark.asyncio
async def test_handler_logs_warning_without_input(app_with_handler, caplog):
    import logging

    transport = ASGITransport(app=app_with_handler)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with caplog.at_level(logging.WARNING):
            await client.post(
                "/test", json={"email": "leaked@phi.example", "name": "x", "irb": "y"}
            )
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "leaked@phi.example" not in log_text, "logger leaked rejected input"
    assert "validation_failed" in log_text
