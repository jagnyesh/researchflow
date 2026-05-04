"""Tests for app/security/body_size.py — CSO Phase 2.3 Finding 1 fix (layer 2).

Defense-in-depth body-size cap that runs BEFORE audit middleware. Catches
oversized requests at the request boundary so they never reach Pydantic
(which would have already allocated memory parsing the JSON).
"""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.security.body_size import body_size_limit_middleware, MAX_REQUEST_BODY_BYTES


@pytest.fixture
def app_with_middleware():
    app = FastAPI()
    app.middleware("http")(body_size_limit_middleware)

    @app.post("/echo")
    async def echo(payload: dict):
        return {"len": len(str(payload))}

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_rejects_oversized_body_with_413(app_with_middleware):
    """Body over MAX_REQUEST_BODY_BYTES gets 413 — never reaches the handler."""
    huge_payload = '{"k": "' + ("x" * (MAX_REQUEST_BODY_BYTES + 1)) + '"}'
    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/echo",
            content=huge_payload,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_accepts_payload_under_cap(app_with_middleware):
    """A 1KB payload is well under the 1MB cap and passes through."""
    payload = '{"k": "' + ("x" * 1000) + '"}'
    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/echo",
            content=payload,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_request_with_no_body_passes_through(app_with_middleware):
    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ping")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_request_without_content_length_passes_through(app_with_middleware):
    """Chunked transfer (no Content-Length) is allowed — Pydantic field caps catch it later.

    Strict body-size enforcement on chunked requests would require buffering, which
    defeats the purpose. The downstream Pydantic LongText/BoundedDict caps catch
    excessively large fields after parse.
    """
    payload = '{"k": "small"}'
    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # httpx adds Content-Length automatically for content; we simulate by
        # using a generator stream which httpx sends as Transfer-Encoding: chunked.
        async def gen():
            yield payload.encode()

        response = await client.post(
            "/echo",
            content=gen(),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_default_cap_is_one_megabyte():
    """Sanity check: default cap is 1MB. Tunable via AUDIT/MAX_REQUEST_BODY_BYTES env."""
    assert MAX_REQUEST_BODY_BYTES == 1_000_000
