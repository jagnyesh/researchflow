import os

import pytest

from app.mcp.store import FileContextStore


def test_mcp_save_load(tmp_path):
    store = FileContextStore(str(tmp_path))
    store.save("r1", {"k": "v"})
    loaded = store.load("r1")
    assert loaded["k"] == "v"


UNSAFE_IDS = ["../escape", "../../escape", "..", ".", "", "sub/escape", "..\\escape", "a\x00b"]


@pytest.mark.parametrize("request_id", UNSAFE_IDS + ["ABSOLUTE"])
def test_save_refuses_a_request_id_that_leaves_the_context_directory(tmp_path, request_id):
    """#223, #468: POST /mcp/context passes a body request_id straight to save()."""
    store = FileContextStore(str(tmp_path / "contexts"))
    if request_id == "ABSOLUTE":
        request_id = str(tmp_path / "absolute")

    with pytest.raises(ValueError):
        store.save(request_id, {"k": "v"})

    written = [p for p in tmp_path.rglob("*.json")]
    assert written == []


@pytest.mark.parametrize("request_id", UNSAFE_IDS + ["ABSOLUTE"])
def test_load_refuses_a_request_id_that_leaves_the_context_directory(tmp_path, request_id):
    (tmp_path / "escape.json").write_text('{"secret": 1}')
    (tmp_path / "absolute.json").write_text('{"secret": 1}')
    store = FileContextStore(str(tmp_path / "contexts"))
    if request_id == "ABSOLUTE":
        request_id = str(tmp_path / "absolute")

    assert store.load(request_id) is None


def test_load_refuses_a_symlink_that_points_outside(tmp_path):
    (tmp_path / "secret.json").write_text('{"secret": 1}')
    store = FileContextStore(str(tmp_path / "contexts"))
    os.symlink(tmp_path / "secret.json", tmp_path / "contexts" / "link.json")

    assert store.load("link") is None


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
@pytest.mark.parametrize("request_id", ["../escape", "../../escape", "ABSOLUTE"])
async def test_post_context_cannot_write_outside_the_context_directory(
    tmp_path, monkeypatch, fake_audit_redis, request_id
):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    work = tmp_path / "a" / "b"
    work.mkdir(parents=True)
    monkeypatch.chdir(work)  # FileContextStore() defaults to ./mcp_contexts
    if request_id == "ABSOLUTE":
        request_id = str(tmp_path / "absolute")

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

    assert response.status_code != 200
    assert [p for p in tmp_path.rglob("*.json")] == []
