"""#478: POST /mcp/context answers a malformed request_id with a 4xx, not a 500."""

import logging

import pytest


@pytest.fixture
async def fake_audit_redis():
    import fakeredis.aioredis

    from app.security import audit_middleware as am

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(client)
    yield client
    am.set_audit_redis(previous)
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_id", ["../xsentinel", "ABSOLUTE", "a\\xsentinel", "a/xsentinel", ".."]
)
async def test_unsafe_request_id_gets_400_without_echo_or_write(
    tmp_path, monkeypatch, fake_audit_redis, caplog, request_id
):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    work = tmp_path / "a" / "b"
    work.mkdir(parents=True)
    monkeypatch.chdir(work)
    if request_id == "ABSOLUTE":
        request_id = str(tmp_path / "xsentinel")

    with caplog.at_level(logging.DEBUG):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            token = (
                await client.post(
                    "/a2a/token", json={"client_id": "agent-x", "client_secret": "agent-x"}
                )
            ).json()["access_token"]
            response = await client.post(
                "/mcp/context",
                json={"request_id": request_id, "context": {"k": "v"}},
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 400
    assert "xsentinel" not in response.text
    assert "xsentinel" not in caplog.text
    assert [p for p in tmp_path.rglob("*.json")] == []
