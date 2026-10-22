"""ViewDefinition writes are admin-only; reads/execution stay open (#178).

Decision (2026-10-21): create/delete of ViewDefinitions is admin-only, like the
materialized-view mutations (#26) — definitions feed SQL generation and
materialization, so writing one is an infrastructure change. Execution stays
open to authenticated researchers: with writes gated they can only run curated
definitions. Same override pattern as test_materialized_views_auth.py.
"""

from functools import partial
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security.dependencies import get_current_active_user

VALID_VIEW = {
    "resourceType": "ViewDefinition",
    "resource": "Patient",
    "name": "authz_view",
    "select": [{"column": [{"path": "id", "name": "id"}]}],
}


def _user(role):
    user = MagicMock()
    user.role, user.email, user.is_active = role, f"{role}@example.com", True
    return user


@pytest.fixture
def client_as(tmp_path, monkeypatch):
    from app.api import analytics
    from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager

    monkeypatch.setattr(
        analytics,
        "ViewDefinitionManager",
        partial(ViewDefinitionManager, view_definitions_dir=str(tmp_path)),
    )

    def make(role):
        app = FastAPI()
        app.include_router(analytics.router)
        app.dependency_overrides[get_current_active_user] = lambda: _user(role)
        return TestClient(app), tmp_path

    return make


@pytest.mark.parametrize("role", ["researcher", "informatician"])
def test_non_admin_cannot_create_or_delete(client_as, role):
    client, views = client_as(role)
    (views / "keep_me.json").write_text('{"placeholder": true}')

    create = client.post("/analytics/view-definitions", json={"view_definition": VALID_VIEW})
    delete = client.delete("/analytics/view-definitions/keep_me")

    assert (create.status_code, delete.status_code) == (403, 403)
    assert not (views / "authz_view.json").exists()
    assert (views / "keep_me.json").exists()


def test_admin_can_create_and_delete(client_as):
    client, views = client_as("admin")

    assert (
        client.post("/analytics/view-definitions", json={"view_definition": VALID_VIEW}).status_code
        == 200
    )
    assert (views / "authz_view.json").exists()
    assert client.delete("/analytics/view-definitions/authz_view").status_code == 200
    assert not (views / "authz_view.json").exists()


def test_researcher_can_still_read(client_as):
    client, views = client_as("admin")
    client.post("/analytics/view-definitions", json={"view_definition": VALID_VIEW})
    client, _ = client_as("researcher")

    assert client.get("/analytics/view-definitions").status_code == 200
    assert client.get("/analytics/view-definitions/authz_view").status_code == 200
