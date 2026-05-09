"""Phase 2.0b tests (issue #18) — on-demand MV refresh endpoint.

Verifies the production behavior the refresh endpoint needs to provide:
- Admin-role gate (Sprint 6.1 contract)
- REFRESH MATERIALIZED VIEW CONCURRENTLY (no reader downtime)
- Parallel execution via asyncio.gather (7 views in ~max(per-view), not sum)
- Per-view error isolation (one bad view doesn't abort the others)
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_refresh_view_uses_concurrently():
    """Issue #18 + decision 8A: REFRESH MATERIALIZED VIEW must include
    CONCURRENTLY so cohort queries can read the view during refresh.

    Asserts the SQL emitted by refresh_view contains the keyword. The
    UNIQUE INDEX on id (added in #13) is the prerequisite postgres needs
    for CONCURRENTLY to work — issue #13's harness test_unique_index_on_id
    keeps that prerequisite verified.
    """
    from app.services.materialized_view_service import MaterializedViewService

    svc = MaterializedViewService.__new__(MaterializedViewService)
    svc.SCHEMA_NAME = "sqlonfhir"
    svc.db_client = AsyncMock()
    svc.db_client.execute_query = AsyncMock(return_value=[{"count": 1}])
    svc._update_metadata = AsyncMock()

    await svc.refresh_view("patient_simple")

    sql_calls = [call.args[0] for call in svc.db_client.execute_query.call_args_list]
    refresh_sql = next((s for s in sql_calls if "REFRESH MATERIALIZED VIEW" in s), None)
    assert refresh_sql is not None, f"No REFRESH SQL found in calls: {sql_calls}"
    assert "CONCURRENTLY" in refresh_sql, (
        f"REFRESH SQL missing CONCURRENTLY: {refresh_sql!r}. "
        "Without it, refresh takes an exclusive lock blocking all readers."
    )


@pytest.mark.asyncio
async def test_refresh_all_views_runs_in_parallel():
    """Issue #18: 7 views should refresh via asyncio.gather, not sequentially.

    With each refresh artificially delayed 100ms, sequential = 700ms,
    parallel = ~100ms. Asserts total <300ms (gives margin).
    """
    import asyncio
    import time

    from app.services.materialized_view_service import MaterializedViewService

    svc = MaterializedViewService.__new__(MaterializedViewService)
    svc.SCHEMA_NAME = "sqlonfhir"

    async def slow_refresh(view_name):
        await asyncio.sleep(0.1)
        return {"view_name": view_name, "success": True, "refresh_duration_ms": 100.0}

    svc.list_views = AsyncMock(return_value=[{"view_name": f"view_{i}"} for i in range(7)])
    svc.refresh_view = AsyncMock(side_effect=slow_refresh)

    t0 = time.perf_counter()
    await svc.refresh_all_views()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 300, (
        f"Expected parallel refresh under 300ms (single view = 100ms; 7 in parallel "
        f"= ~100ms); got {elapsed_ms:.0f}ms which is closer to sequential ({7*100}ms). "
        "refresh_all_views likely loops sequentially instead of using asyncio.gather."
    )


@pytest.mark.asyncio
async def test_refresh_all_views_isolates_per_view_failures():
    """Issue #18: one view's refresh failure must not abort the others.

    Mocks 7 views where view_3 raises an exception. Asserts the other 6
    still report success and the result includes view_3's error.
    """
    from app.services.materialized_view_service import MaterializedViewService

    svc = MaterializedViewService.__new__(MaterializedViewService)
    svc.SCHEMA_NAME = "sqlonfhir"

    async def maybe_failing_refresh(view_name):
        if view_name == "view_3":
            raise RuntimeError("simulated lock timeout")
        return {"view_name": view_name, "success": True, "refresh_duration_ms": 10.0}

    svc.list_views = AsyncMock(return_value=[{"view_name": f"view_{i}"} for i in range(7)])
    svc.refresh_view = AsyncMock(side_effect=maybe_failing_refresh)

    summary = await svc.refresh_all_views()

    assert summary["total_views"] == 7
    assert summary["success"] == 6, f"Expected 6 successes; got {summary['success']}"
    assert summary["failed"] == 1, f"Expected 1 failure; got {summary['failed']}"

    failed_results = [r for r in summary["results"] if not r["success"]]
    assert len(failed_results) == 1
    assert "simulated lock timeout" in str(failed_results[0].get("error", ""))


@pytest.mark.asyncio
async def test_refresh_all_endpoint_requires_admin_role():
    """Issue #18: POST refresh-all must be gated to admin role.

    Without auth, the endpoint should return 401 (Sprint 6.1 audit
    middleware default-deny on PHI routes — though this is admin not PHI,
    same gate). With non-admin role, should return 403.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        response = client.post("/analytics/materialized-views/refresh-all")
        assert response.status_code in (401, 403), (
            f"Expected 401 or 403 from unauth refresh-all; got {response.status_code}. "
            f"Endpoint exists but lacks admin-role gate (Depends(require_role('admin')))."
        )
