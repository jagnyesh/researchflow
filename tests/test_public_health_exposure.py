"""Public /health reports status only (#179).

`/health` is unauthenticated (NO_AUDIT allowlist). It returned the internal
FHIR_BASE_URL and research_requests counts; same rule as the public
/health/ready probe (Finding 2, test_audit_health.py): status, not intel.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.health import FHIR_BASE_URL
from app.api.health import router as health_router


@pytest.fixture
def health_app():
    app = FastAPI()
    app.include_router(health_router)
    return app


@pytest.mark.asyncio
async def test_public_health_exposes_only_component_status(health_app):
    from app.database import init_db

    await init_db()  # real SQLite test DB, so the healthy-database branch runs

    async with AsyncClient(transport=ASGITransport(app=health_app), base_url="http://test") as c:
        resp = await c.get("/health")

    body = resp.json()
    assert FHIR_BASE_URL not in resp.text
    assert set(body) <= {"status", "timestamp", "components"}
    assert body["components"], "expected per-component status"
    for name, component in body["components"].items():
        assert set(component) <= {
            "status",
            "error",
        }, f"{name} leaks {set(component) - {'status', 'error'}}"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
async def test_other_public_probes_expose_no_detail(health_app, path):
    async with AsyncClient(transport=ASGITransport(app=health_app), base_url="http://test") as c:
        resp = await c.get(path)

    assert FHIR_BASE_URL not in resp.text
    assert set(resp.json()) <= {"status", "timestamp"}
