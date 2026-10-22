"""ViewDefinition names must never escape the ViewDefinition directory (#177).

`ViewDefinitionManager` turns a caller-supplied name into
`<dir>/{name}.json`; `POST /analytics/view-definitions` passes the request's
`name` straight through, and only `view_definition["name"]` was validated.
"""

import os
from datetime import timedelta
from functools import partial

import fakeredis.aioredis
import pytest

os.environ.setdefault("ENABLE_ORCHESTRATOR", "false")

VALID_VIEW = {
    "resourceType": "ViewDefinition",
    "resource": "Patient",
    "name": "safe_view",
    "select": [{"column": [{"path": "id", "name": "id"}]}],
}


@pytest.fixture
async def fake_audit_redis():
    from app.security import audit_middleware as am

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(client)
    yield client
    am.set_audit_redis(previous)
    await client.aclose()


@pytest.fixture
def view_dir(tmp_path, monkeypatch):
    """Point the API's ViewDefinitionManager at <tmp>/views; <tmp> is the
    'outside' a traversal would reach."""
    from app.api import analytics
    from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager

    views = tmp_path / "views"
    monkeypatch.setattr(
        analytics,
        "ViewDefinitionManager",
        partial(ViewDefinitionManager, view_definitions_dir=str(views)),
    )
    return views


@pytest.fixture
def auth_headers():
    from app.security.auth import create_access_token

    token = create_access_token(
        {"sub": "vd@example.com", "user_id": "vd-1", "role": "researcher"},
        expires_delta=timedelta(minutes=5),
    )
    return {"authorization": f"Bearer {token}"}


async def _client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["../escaped", "x/../../escaped"])
async def test_create_rejects_traversal_name_and_writes_nothing_outside(
    fake_audit_redis, view_dir, auth_headers, name
):
    async with await _client() as client:
        resp = await client.post(
            "/analytics/view-definitions",
            json={"view_definition": VALID_VIEW, "name": name},
            headers=auth_headers,
        )

    assert resp.status_code == 400
    assert not (view_dir.parent / "escaped.json").exists()
    assert list(view_dir.parent.rglob("*.json")) == []


def _plant_outside(view_dir, stem="secret"):
    """A valid ViewDefinition one level above the directory — what a
    traversal would read or delete."""
    import json

    view_dir.mkdir(parents=True, exist_ok=True)
    target = view_dir.parent / f"{stem}.json"
    target.write_text(json.dumps({**VALID_VIEW, "name": stem}))
    return target


# Letter-first cases matter: a prefix `match` (vs `fullmatch`) accepts them.
TRAVERSALS = [
    "../secret",
    "..\\secret",
    "{abs}",
    "sec\x00ret",
    "./../secret",
    "x/../../secret",
    "abc\x00",
]


@pytest.mark.parametrize("name", TRAVERSALS)
def test_load_refuses_names_outside_the_directory(tmp_path, name):
    from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager

    views = tmp_path / "views"
    target = _plant_outside(views)
    manager = ViewDefinitionManager(view_definitions_dir=str(views))

    with pytest.raises(FileNotFoundError):
        manager.load(name.format(abs=str(target.with_suffix(""))))


@pytest.mark.asyncio
async def test_execute_with_traversal_view_name_is_404(fake_audit_redis, view_dir, auth_headers):
    """`view_name` is a body field, so separators reach the handler intact
    (unlike a path param, where an encoded `/` never routes)."""
    _plant_outside(view_dir)
    async with await _client() as client:
        resp = await client.post(
            "/analytics/execute", json={"view_name": "../secret"}, headers=auth_headers
        )

    assert resp.status_code == 404


@pytest.mark.parametrize("name", TRAVERSALS)
def test_delete_refuses_names_outside_the_directory(tmp_path, name):
    from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager

    views = tmp_path / "views"
    target = _plant_outside(views)
    manager = ViewDefinitionManager(view_definitions_dir=str(views))

    assert manager.delete(name.format(abs=str(target.with_suffix("")))) is False
    assert target.exists()


def test_shipped_view_definitions_still_load():
    """The name rule must not orphan any definition already in the library."""
    from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager

    manager = ViewDefinitionManager()
    names = manager.list()
    assert names, "expected the shipped ViewDefinition library"
    assert set(manager.load_all()) == set(names)


@pytest.mark.asyncio
async def test_overlong_name_is_404_not_500(fake_audit_redis, view_dir, auth_headers):
    """Path params are uncapped; past the OS name limit `exists()` raised
    ENAMETOOLONG → 500. Names are capped at Postgres's 63-char identifier."""
    async with await _client() as client:
        resp = await client.get("/analytics/view-definitions/" + "a" * 300, headers=auth_headers)

    assert resp.status_code == 404
