"""/analytics/health reports status, never the FHIR base URL (#446).

The route returned `fhir_client.base_url`, so a `FHIR_SERVER_URL` with
credentials in its userinfo handed them to the caller. Same rule as the public
/health probe (#179, test_public_health_exposure.py): status, not intel.
"""

import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.analytics import router as analytics_router

# Canary userinfo, not a credential for anything.
CANARY_USER = "canary-user-446"
CANARY_PASSWORD = "canary-pass-446"  # pragma: allowlist secret


async def _analytics_health(monkeypatch, fhir_server_url):
    monkeypatch.setenv("FHIR_SERVER_URL", fhir_server_url)
    app = FastAPI()
    app.include_router(analytics_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get("/analytics/health")


@pytest.mark.asyncio
async def test_connected_health_returns_no_part_of_the_fhir_url(monkeypatch):
    # A stub answers /metadata, so the connected branch runs without a live HAPI.
    async def capability_statement(reader, writer):
        await reader.readline()
        body = b'{"resourceType": "CapabilityStatement"}'
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/fhir+json\r\n"
            b"Content-Length: %d\r\nConnection: close\r\n\r\n%s" % (len(body), body)
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(capability_statement, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        resp = await _analytics_health(
            monkeypatch,
            f"http://{CANARY_USER}:{CANARY_PASSWORD}@127.0.0.1:{port}/fhir-path-canary-446",
        )
    finally:
        server.close()

    assert resp.json()["fhir_server_connected"] is True
    assert CANARY_USER not in resp.text
    assert CANARY_PASSWORD not in resp.text
    assert "fhir-path-canary-446" not in resp.text
    assert f"127.0.0.1:{port}" not in resp.text


# Nothing listens on port 1, so the probe fails fast. The last two are mistyped
# credentials that urlsplit reads as host, port or path instead of userinfo.
@pytest.mark.parametrize(
    "fhir_server_url",
    [
        f"http://{CANARY_USER}:{CANARY_PASSWORD}@127.0.0.1:1/fhir-path-canary-446",
        f"http://{CANARY_USER}:{CANARY_PASSWORD}/slash-canary-446@127.0.0.1:1/fhir",
        f"http://{CANARY_USER}:{CANARY_PASSWORD}%40127.0.0.1:1/fhir",
    ],
    ids=["userinfo", "slash-in-password", "percent-encoded-at"],
)
@pytest.mark.asyncio
async def test_unreachable_health_returns_status_fields_only(monkeypatch, fhir_server_url):
    resp = await _analytics_health(monkeypatch, fhir_server_url)

    body = resp.json()
    assert body["status"] in {"degraded", "unhealthy"}
    assert "canary" not in resp.text
    assert set(body) <= {"status", "fhir_server_connected", "error"}
