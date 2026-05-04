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
    # Explicit override: .env points DATABASE_URL at the docker Postgres which
    # may have stale schema. Use SQLite test.db for E2E so audit_logs schema
    # matches the current AuditLog model.
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"

    from datetime import timedelta
    from httpx import AsyncClient, ASGITransport
    from sqlalchemy import select
    from app.main import app, lifespan
    from app.database import get_db_session
    from app.database.models import AuditLog
    from app.adapters.sql_on_fhir import SQLonFHIRAdapter
    from app.security.auth import create_access_token

    async def stub_execute(self, sql):
        return [{"col": "value"}]

    SQLonFHIRAdapter.execute_sql = stub_execute

    token = create_access_token(
        {"sub": "e2e@example.com", "user_id": "e2e-user", "role": "researcher"},
        expires_delta=timedelta(minutes=5),
    )

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/sql_query",
                json={"sql": "SELECT 1"},
                headers={"authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200, f"got {response.status_code}: {response.text}"

        # Poll for the audit rows to appear (drain runs at ~10Hz). Issue #2 emits
        # both a pre-event (PHI_ACCESS_REQUESTED) and post-event (PHI_ACCESS_COMPLETED).
        deadline = asyncio.get_event_loop().time() + 5.0
        pre_seen = post_seen = 0
        while asyncio.get_event_loop().time() < deadline:
            async with get_db_session() as session:
                result = await session.execute(
                    select(AuditLog).where(AuditLog.user_id == "e2e-user")
                )
                rows = result.scalars().all()
            pre_seen = sum(1 for r in rows if r.event_type == "PHI_ACCESS_REQUESTED")
            post_seen = sum(1 for r in rows if r.event_type == "PHI_ACCESS_COMPLETED")
            if pre_seen >= 1 and post_seen >= 1:
                break
            await asyncio.sleep(0.1)

        assert pre_seen >= 1, "PHI_ACCESS_REQUESTED row did not appear within 5s"
        assert post_seen >= 1, "PHI_ACCESS_COMPLETED row did not appear within 5s"
