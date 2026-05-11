"""Regression tests for issue #26: materialized_views.py router hardening.

Pins three behaviors:

1. All 5 mutating endpoints (POST /{view_name}/refresh, POST /refresh-all,
   POST /refresh-stale, POST /create-all, DELETE /{view_name}) reject
   non-admin callers with 403.
2. Path-param routes (POST /{view_name}/refresh, DELETE /{view_name})
   reject unknown view names with 404, including SQL injection payloads
   that would otherwise reach f-string interpolation.
3. The injection payload never reaches db_client.execute_query — the
   allowlist short-circuits before any SQL is built.

All tests use FastAPI dependency_overrides to swap require_role + the
service factory, so no real Postgres / Redis / HAPI is needed.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.materialized_views import router, _validate_view_name
from app.security.dependencies import get_current_active_user


# ----- Fixtures -----
#
# require_role(role) returns a NEW role_checker function instance each call,
# so dependency_overrides keyed on require_role("admin") don't match the
# instance the routes captured at import time. Override the INNER dependency
# get_current_active_user instead — every role_checker delegates to it, so
# one override covers all 5 admin-gated routes.


def _make_user(role: str, email: str):
    user = MagicMock()
    user.role = role
    user.email = email
    user.is_active = True
    return user


@pytest.fixture
def app_with_admin():
    """FastAPI app where get_current_active_user returns an admin."""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_active_user] = lambda: _make_user(
        "admin", "admin-test@example.com"
    )
    return app


@pytest.fixture
def app_with_researcher():
    """FastAPI app where get_current_active_user returns a non-admin researcher.

    role_checker (from require_role) will then raise 403 because researcher
    role != admin. This proves the role gate fires, not just the auth gate.
    """
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_active_user] = lambda: _make_user(
        "researcher", "researcher-test@example.com"
    )
    return app


# ----- Test 1: non-admin gets 403 on every mutating endpoint -----


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/analytics/materialized-views/patient_demographics/refresh"),
        ("POST", "/analytics/materialized-views/refresh-all"),
        ("POST", "/analytics/materialized-views/refresh-stale"),
        ("POST", "/analytics/materialized-views/create-all"),
        ("DELETE", "/analytics/materialized-views/patient_demographics"),
    ],
)
def test_non_admin_blocked_on_mutating_endpoints(app_with_researcher, method, path):
    """Researcher token must NOT be able to fire any mutating endpoint."""
    client = TestClient(app_with_researcher)
    response = client.request(method, path)
    assert (
        response.status_code == 403
    ), f"{method} {path} should reject non-admin with 403; got {response.status_code}: {response.text}"


# ----- Test 2: GETs are NOT admin-gated -----


@pytest.mark.parametrize(
    "path",
    [
        "/analytics/materialized-views/",
        "/analytics/materialized-views/health",
    ],
)
def test_read_only_endpoints_not_admin_gated(app_with_researcher, path):
    """GET / and GET /health stay reader-accessible (no admin requirement).

    Asserts the dep-graph: if these were admin-gated, the researcher fixture
    (which raises 403 from require_role) would fire even before any handler
    code runs. We assert "not 403" — the actual handler may still 5xx if it
    needs a DB, but it must not be auth-blocked.
    """
    client = TestClient(app_with_researcher)
    response = client.get(path)
    assert (
        response.status_code != 403
    ), f"GET {path} should NOT be admin-gated; got 403: {response.text}"


# ----- Test 3: SQL injection payloads return 404, never reach SQL layer -----


@pytest.mark.parametrize(
    "view_name",
    [
        "x;DROP TABLE users;--",
        "patient_demographics; DROP TABLE research_requests; --",
        "../etc/passwd",
        "PATIENT_DEMOGRAPHICS",  # uppercase rejected by regex
        "1numeric_start",  # must start with letter
        "with-hyphen",  # only underscore allowed
        "with space",
        "'; SELECT * FROM users; --",
        "name)/*",
    ],
)
def test_view_name_injection_rejected_with_404(app_with_admin, view_name):
    """Allowlist + regex must reject every injection payload as 404.

    Hits the DELETE endpoint (which would f-string interpolate into a
    DROP MATERIALIZED VIEW statement). Mocks the service so any path that
    does reach it raises a clear marker — but the 404 should fire BEFORE
    the service is touched.
    """
    client = TestClient(app_with_admin)

    with patch("app.api.materialized_views.get_service") as mock_get_service:
        # If we ever reach get_service(), the test should fail loudly
        mock_get_service.side_effect = AssertionError(
            "INJECTION REACHED SQL LAYER — _validate_view_name did not block "
            f"view_name={view_name!r}"
        )

        # URL-encode the path segment so FastAPI routes correctly
        from urllib.parse import quote

        path = f"/analytics/materialized-views/{quote(view_name, safe='')}"
        response = client.request("DELETE", path)

        assert response.status_code == 404, (
            f"DELETE {path} should return 404 for view_name={view_name!r}; "
            f"got {response.status_code}: {response.text}"
        )
        # And get_service was never called — proves the SQL layer wasn't reached
        mock_get_service.assert_not_called()


# ----- Test 4: refresh path also rejects injection -----


def test_refresh_view_injection_rejected_with_404(app_with_admin):
    """POST /{view_name}/refresh must also block injection payloads."""
    client = TestClient(app_with_admin)

    with patch("app.api.materialized_views.get_service") as mock_get_service:
        mock_get_service.side_effect = AssertionError("INJECTION REACHED SQL LAYER")
        from urllib.parse import quote

        payload = "x;DROP TABLE users;--"
        path = f"/analytics/materialized-views/{quote(payload, safe='')}/refresh"
        response = client.request("POST", path)

        assert response.status_code == 404
        mock_get_service.assert_not_called()


# ----- Test 5: _validate_view_name unit-level smoke test -----


def test_validate_view_name_accepts_real_view():
    """Real view defs from app/sql_on_fhir/view_definitions/*.json must pass."""
    # patient_demographics is a known view def file
    _validate_view_name("patient_demographics")  # must not raise


def test_validate_view_name_rejects_unknown():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _validate_view_name("nonexistent_view_name")
    assert exc.value.status_code == 404


def test_validate_view_name_rejects_injection_via_regex():
    """Regex layer rejects identifiers that ARE valid filename stems but
    contain non-allowlist characters. Belt-and-suspenders for if someone
    drops a malformed JSON file under view_definitions/ in the future.
    """
    from fastapi import HTTPException

    for bad in ["DROP TABLE users", "x; DROP", "1starts_with_digit", "UPPERCASE"]:
        with pytest.raises(HTTPException) as exc:
            _validate_view_name(bad)
        assert exc.value.status_code == 404, f"Expected 404 for {bad!r}"
