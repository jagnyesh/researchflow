"""
Tests for the route-template-to-resource map (Sprint 6.1 Phase 2.2 - Issue #2).

Best-effort resource_type/resource_id population for the typed AuditLog columns.
Unmapped PHI routes log a warning and emit the event with null resource_id.
"""

import pytest

from app.security.audit_middleware import resolve_resource, RESOURCE_MAP


def test_resource_map_covers_known_phi_route_prefixes():
    expected = {
        "/research",
        "/sql_query",
        "/analytics",
        "/approvals",
        "/users",
        "/mcp",
        "/a2a",
        "/auth",
    }
    assert expected.issubset(set(RESOURCE_MAP.keys()))


def test_resolve_resource_returns_type_for_known_prefix_no_id():
    rt, rid = resolve_resource("/sql_query")
    assert rt == "Query"
    assert rid is None


def test_resolve_resource_extracts_uuid_like_id():
    rt, rid = resolve_resource("/research/abc-12345")
    assert rt == "ResearchRequest"
    assert rid == "abc-12345"


def test_resolve_resource_extracts_numeric_id():
    rt, rid = resolve_resource("/users/42")
    assert rt == "User"
    assert rid == "42"


def test_resolve_resource_skips_verb_segments():
    """`/analytics/execute` is a verb route, not a resource lookup; resource_id stays None."""
    rt, rid = resolve_resource("/analytics/execute")
    assert rt == "AnalyticsView"
    assert rid is None


def test_resolve_resource_returns_none_for_unmapped_path():
    rt, rid = resolve_resource("/some/random/path/never/seen")
    assert rt is None
    assert rid is None


def test_resolve_resource_handles_root_path():
    rt, rid = resolve_resource("/")
    assert rt is None
    assert rid is None


def test_unmapped_phi_route_logs_warning(caplog):
    """If a PHI route isn't in RESOURCE_MAP, middleware logs a warning."""
    import logging
    from app.security.audit_middleware import warn_if_unmapped_phi_route, classify_route, RouteClass

    assert classify_route("/some/never/seen") is RouteClass.PHI
    with caplog.at_level(logging.WARNING):
        warn_if_unmapped_phi_route("/some/never/seen")
    assert any("/some/never/seen" in r.message for r in caplog.records)


def test_warn_does_not_fire_for_mapped_phi_route(caplog):
    import logging
    from app.security.audit_middleware import warn_if_unmapped_phi_route

    with caplog.at_level(logging.WARNING):
        warn_if_unmapped_phi_route("/research/abc-123")
    assert not any("research" in r.message.lower() for r in caplog.records)
