"""
End-to-end test for Phase 2.2 Issue #1 (tracer bullet).

Hits POST /sql_query through the real FastAPI app, with the real audit Redis
instance (`redis-audit` docker service) and Postgres backing audit_logs.
Skipped automatically if the audit Redis port (6380) is not reachable —
run after `docker-compose up redis-audit db`.
"""

import os
import asyncio
import socket
import pytest


def _audit_redis_reachable() -> bool:
    host, port = "localhost", 6380
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


pytestmark = pytest.mark.skipif(
    not _audit_redis_reachable(),
    reason="redis-audit (localhost:6380) not running; start via `docker-compose up redis-audit`",
)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_sql_query_produces_audit_row():
    os.environ["REDIS_AUDIT_URL"] = "redis://localhost:6380/0"
    os.environ["ENABLE_ORCHESTRATOR"] = "false"

    from httpx import AsyncClient, ASGITransport
    from sqlalchemy import select
    from app.main import app, lifespan
    from app.database import get_db_session
    from app.database.models import AuditLog
    from app.adapters.sql_on_fhir import SQLonFHIRAdapter

    async def stub_execute(self, sql):
        return [{"col": "value"}]

    SQLonFHIRAdapter.execute_sql = stub_execute

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/sql_query", json={"sql": "SELECT 1"})

        assert response.status_code == 200

        # Poll for the audit row to appear (drain runs at ~10Hz)
        deadline = asyncio.get_event_loop().time() + 5.0
        seen = 0
        while asyncio.get_event_loop().time() < deadline:
            async with get_db_session() as session:
                result = await session.execute(
                    select(AuditLog).where(AuditLog.event_type == "PHI_ACCESS")
                )
                rows = result.scalars().all()
            seen = len(rows)
            if seen >= 1:
                break
            await asyncio.sleep(0.1)

        assert seen >= 1, "audit row did not appear in audit_logs within 5s"
