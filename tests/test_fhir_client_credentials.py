"""#445: userinfo in FHIR_SERVER_URL must not reach any log record or exception text.

httpx logs the full request URL at INFO, so the leak is in httpx's own logging.
These tests therefore run FHIRClient against a real stub server on 127.0.0.1 and
capture every record on the root logger; a mocked httpx client would hide it.
"""

import base64
import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.clients.fhir_client import FHIRClient

USER = "CANARYUSER"
PASSWORD = "CANARYPASS"


class _Handler(BaseHTTPRequestHandler):
    seen_auth: list = []

    def do_GET(self):
        type(self).seen_auth.append(self.headers.get("Authorization"))
        status = 404 if "/missing/" in self.path else 200
        body = json.dumps({"resourceType": "CapabilityStatement"}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def stub_server():
    handler = type("H", (_Handler,), {"seen_auth": []})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port, handler
    server.shutdown()
    server.server_close()


def _free_closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _logged_text(caplog) -> str:
    parts = []
    for r in caplog.records:
        parts.append(r.getMessage())
        if r.exc_info:
            parts.append(logging.Formatter().formatException(r.exc_info))
        if r.exc_text:
            parts.append(r.exc_text)
    return "\n".join(parts)


def _assert_no_canary(text: str):
    low = text.lower()
    assert USER.lower() not in low
    assert PASSWORD.lower() not in low


async def test_success_path_logs_no_userinfo_and_authenticates(stub_server, caplog):
    port, handler = stub_server
    caplog.set_level(logging.DEBUG)
    client = FHIRClient(base_url=f"http://{USER}:{PASSWORD}@127.0.0.1:{port}/fhir")
    try:
        await client.get_metadata()
    finally:
        await client.close()

    # Guard against a vacuous pass: httpx's own record must have been captured.
    assert any(r.name == "httpx" for r in caplog.records)
    _assert_no_canary(_logged_text(caplog))
    expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    assert handler.seen_auth == [expected]


async def test_percent_encoded_credentials_are_decoded_for_auth(stub_server, caplog):
    port, handler = stub_server
    caplog.set_level(logging.DEBUG)
    client = FHIRClient(base_url=f"http://{USER}:p%40ss%3Aword@127.0.0.1:{port}/fhir")
    try:
        await client.get_metadata()
    finally:
        await client.close()

    expected = "Basic " + base64.b64encode(f"{USER}:p@ss:word".encode()).decode()
    assert handler.seen_auth == [expected]
    low = _logged_text(caplog).lower()
    assert "p%40ss" not in low and "p@ss" not in low


async def test_non_2xx_leaks_nothing_in_logs_or_exception(stub_server, caplog):
    port, _ = stub_server
    caplog.set_level(logging.DEBUG)
    client = FHIRClient(base_url=f"http://{USER}:{PASSWORD}@127.0.0.1:{port}/fhir/missing")
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await client.get_metadata()
    finally:
        await client.close()

    _assert_no_canary(_logged_text(caplog))
    _assert_no_canary(str(exc.value))


async def test_connection_error_leaks_nothing(caplog):
    caplog.set_level(logging.DEBUG)
    client = FHIRClient(base_url=f"http://{USER}:{PASSWORD}@127.0.0.1:{_free_closed_port()}/fhir")
    try:
        with pytest.raises(httpx.ConnectError) as exc:
            await client.get_metadata()
    finally:
        await client.close()

    _assert_no_canary(_logged_text(caplog))
    _assert_no_canary(str(exc.value))


async def test_url_without_userinfo_sends_no_authorization(stub_server):
    port, handler = stub_server
    client = FHIRClient(base_url=f"http://127.0.0.1:{port}/fhir")
    try:
        await client.get_metadata()
    finally:
        await client.close()

    assert handler.seen_auth == [None]
