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


def _auth_headers(role):
    from app.security.auth import create_access_token

    token = create_access_token(
        {"sub": f"{role}@example.com", "user_id": f"{role}-1", "role": role},
        expires_delta=timedelta(minutes=5),
    )
    return {"authorization": f"Bearer {token}"}


@pytest.fixture
def researcher_headers():
    return _auth_headers("researcher")


@pytest.fixture
def admin_headers():
    """Create is admin-only (#178): as a researcher it 403s before the name is
    checked, so the traversal tests must run as admin."""
    return _auth_headers("admin")


async def _client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["../escaped", "x/../../escaped"])
async def test_create_rejects_traversal_name_and_writes_nothing_outside(
    fake_audit_redis, view_dir, admin_headers, name
):
    # Without `x`, an unguarded save of `x/../../escaped` fails on open() and
    # the no-write assertions below could never catch the escape.
    (view_dir / "x").mkdir(parents=True)
    async with await _client() as client:
        resp = await client.post(
            "/analytics/view-definitions",
            json={"view_definition": VALID_VIEW, "name": name},
            headers=admin_headers,
        )

    assert resp.status_code == 400
    assert not (view_dir.parent / "escaped.json").exists()
    assert list(view_dir.parent.rglob("*.json")) == []


@pytest.mark.asyncio
async def test_researcher_create_with_traversal_name_is_403_and_writes_nothing(
    fake_audit_redis, view_dir, researcher_headers
):
    """A real JWT through the full app: test_view_definition_authz.py overrides
    the user dependency, so only this pins role resolution from the token."""
    async with await _client() as client:
        resp = await client.post(
            "/analytics/view-definitions",
            json={"view_definition": VALID_VIEW, "name": "../escaped"},
            headers=researcher_headers,
        )

    assert resp.status_code == 403
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
async def test_execute_with_traversal_view_name_is_404(
    fake_audit_redis, view_dir, researcher_headers
):
    """`view_name` is a body field, so separators reach the handler intact
    (unlike a path param, where an encoded `/` never routes)."""
    _plant_outside(view_dir)
    async with await _client() as client:
        resp = await client.post(
            "/analytics/execute", json={"view_name": "../secret"}, headers=researcher_headers
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
async def test_overlong_name_is_404_not_500(fake_audit_redis, view_dir, researcher_headers):
    """Path params are uncapped; past the OS name limit `exists()` raised
    ENAMETOOLONG → 500. Names are capped at Postgres's 63-char identifier."""
    async with await _client() as client:
        resp = await client.get(
            "/analytics/view-definitions/" + "a" * 300, headers=researcher_headers
        )

    assert resp.status_code == 404
