"""
Tests for the route classifier (Sprint 6.1 Phase 2.2 - Issue #2).

Default-deny: every route is PHI unless explicitly allowlisted.
"""

import pytest

from app.security.audit_middleware import (
    classify_route,
    NO_AUDIT_ALLOWLIST,
    NON_AUTH_ALLOWLIST,
    RouteClass,
)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/health",
        "/health/live",
        "/health/ready",
        "/docs",
        "/docs/",
        "/openapi.json",
        "/redoc",
    ],
)
def test_no_audit_allowlist_paths_classify_as_no_audit(path):
    assert classify_route(path) is RouteClass.NO_AUDIT


@pytest.mark.parametrize(
    "path",
    ["/auth/login", "/auth/refresh", "/auth/logout", "/a2a/token"],
)
def test_non_auth_allowlist_paths_are_audited_without_auth(path):
    assert classify_route(path) is RouteClass.NON_AUTH_AUDITED


@pytest.mark.parametrize(
    "path",
    [
        "/sql_query",
        "/research/abc-123",
        "/research/abc-123/delivery",
        "/analytics/execute",
        "/analytics/materialized-views/foo/refresh",
        "/approvals/pending",
        "/users",
        "/users/abc-123",
        "/mcp/context",
        "/some/path/never/seen/before",
    ],
)
def test_default_deny_treats_unknown_routes_as_phi(path):
    assert classify_route(path) is RouteClass.PHI


def test_no_audit_set_is_subset_of_non_auth_set():
    """If a path skips audit, it must also skip auth (you can't audit nothing)."""
    assert NO_AUDIT_ALLOWLIST.issubset(NON_AUTH_ALLOWLIST)


def test_classifier_handles_trailing_slash_consistently():
    assert classify_route("/health") is RouteClass.NO_AUDIT
    assert classify_route("/health/") is RouteClass.NO_AUDIT
