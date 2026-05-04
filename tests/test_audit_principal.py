"""
Tests for principal resolution (Sprint 6.1 Phase 2.2 - Issue #2).

Middleware-side token decode for the pre-event fail-closed gate. Routes prefixed
with /a2a or /mcp use the service-token verifier; everything else uses the
human JWT decoder.
"""

import pytest
from datetime import timedelta
from unittest.mock import MagicMock

from app.security.audit_middleware import resolve_principal, Principal
from app.security.auth import create_access_token
from app.a2a.auth import issue_token, verify_service_token


def _make_request(path: str, auth_header: str | None = None):
    request = MagicMock()
    request.url.path = path
    request.headers = {"authorization": auth_header} if auth_header else {}
    return request


# --- service-token verification ---


def test_verify_service_token_returns_client_id_for_valid_token():
    token = issue_token("agent-x", "agent-x")
    assert verify_service_token(token) == "agent-x"


def test_verify_service_token_returns_none_for_garbage():
    assert verify_service_token("not-a-token") is None


def test_verify_service_token_returns_none_for_empty():
    assert verify_service_token("") is None


# --- principal resolution ---


def test_resolve_principal_returns_none_when_no_authorization_header():
    request = _make_request("/sql_query")
    assert resolve_principal(request) is None


def test_resolve_principal_returns_user_principal_for_human_jwt():
    token = create_access_token(
        {"sub": "user@example.com", "user_id": "user-42", "role": "researcher"},
        expires_delta=timedelta(minutes=5),
    )
    request = _make_request("/sql_query", auth_header=f"Bearer {token}")
    principal = resolve_principal(request)
    assert principal is not None
    assert principal.user_id == "user-42"
    assert principal.kind == "user"
    assert principal.role == "researcher"


def test_resolve_principal_returns_service_principal_for_a2a_route():
    token = issue_token("agent-x", "agent-x")
    request = _make_request("/a2a/dispatch", auth_header=f"Bearer {token}")
    principal = resolve_principal(request)
    assert principal is not None
    assert principal.user_id == "agent-x"
    assert principal.kind == "service"


def test_resolve_principal_returns_service_principal_for_mcp_route():
    token = issue_token("agent-y", "agent-y")
    request = _make_request("/mcp/context", auth_header=f"Bearer {token}")
    principal = resolve_principal(request)
    assert principal is not None
    assert principal.user_id == "agent-y"
    assert principal.kind == "service"


def test_resolve_principal_returns_none_for_invalid_jwt_on_phi_route():
    request = _make_request("/sql_query", auth_header="Bearer total-garbage")
    assert resolve_principal(request) is None


def test_resolve_principal_returns_none_for_jwt_passed_to_a2a_route():
    """Cross-token rejection: human JWT must not authorize service routes."""
    token = create_access_token(
        {"sub": "user@example.com", "user_id": "user-1", "role": "researcher"}
    )
    request = _make_request("/a2a/dispatch", auth_header=f"Bearer {token}")
    assert resolve_principal(request) is None


def test_resolve_principal_handles_missing_bearer_prefix():
    request = _make_request("/sql_query", auth_header="just-a-token")
    assert resolve_principal(request) is None
