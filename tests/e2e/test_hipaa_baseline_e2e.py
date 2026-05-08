"""End-to-end test for the Sprint 6.1 HIPAA baseline (Phase 4).

Walks one PHI-bearing request through every Sprint 6.1 control in execution
order and asserts each one fired:

  1. body_size middleware accepted the request                (Phase 2.3 layer 2)
  2. audit middleware emitted PHI_ACCESS_REQUESTED            (Phase 2.2 pre)
  3. JWT was decoded → principal landed on the audit row      (Phase 1.1 + 2.2)
  4. Pydantic validated the body via PHIInputModel            (Phase 2.3 framework)
  5. ResearchRequest row written, initial_request encrypted   (Phase 3b)
  6. audit middleware emitted PHI_ACCESS_COMPLETED            (Phase 2.2 post)
  7. drain task flushed both events to audit_logs             (Phase 2.2 durability)

Plus a negative-path tracer:

  8. malformed body → 422 with `input` stripped from response (Phase 2.3 PHI-safe handler)

Skipped automatically if the audit Redis port (6380) is not reachable —
run after `docker-compose up redis-audit db` (or `make docker-up`).
"""

import os
import asyncio
import socket

import pytest


def _audit_redis_reachable() -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.connect(("localhost", 6380))
        return True
    except OSError:
        return False
    finally:
        sock.close()


pytestmark = pytest.mark.skipif(
    not _audit_redis_reachable(),
    reason="redis-audit (localhost:6380) not running; start via `docker-compose up redis-audit`",
)


PHI_NEEDLE = "patient ABC-123 has HbA1c 9.2% on 2025-12-04"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_phi_request_traverses_all_controls():
    os.environ["REDIS_AUDIT_URL"] = "redis://localhost:6380/0"
    os.environ["ENABLE_ORCHESTRATOR"] = "false"
    # Use the same SQLite test DB as other E2E tests; the docker Postgres may
    # have stale schema from prior sprints.
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"

    from datetime import timedelta

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import select, text

    from app.database import get_db_session, get_engine
    from app.database.models import AuditLog
    from app.main import app, lifespan
    from app.security.auth import create_access_token

    token = create_access_token(
        {"sub": "e2e-baseline@example.com", "user_id": "e2e-baseline-user", "role": "researcher"},
        expires_delta=timedelta(minutes=5),
    )

    body = {
        "researcher_name": "Dr. Baseline",
        "researcher_email": "e2e-baseline@example.com",
        "irb_number": "IRB-2026-0001",
        "initial_request": PHI_NEEDLE,
    }

    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # ---------- (1)–(6) golden path ---------------------------------
            response = await client.post(
                "/research/submit",
                json=body,
                headers={"authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200, f"got {response.status_code}: {response.text}"
            request_id = response.json()["request_id"]

            # ---------- (5) encryption-at-rest verification -----------------
            # Bypass the ORM column type and read the raw bytes the DB stored.
            engine = get_engine()
            async with engine.connect() as conn:
                raw = (
                    await conn.execute(
                        text("SELECT initial_request FROM research_requests WHERE id = :id"),
                        {"id": request_id},
                    )
                ).scalar_one()
            decoded = raw if isinstance(raw, str) else raw.decode("latin-1", errors="replace")
            assert (
                PHI_NEEDLE not in decoded
            ), "Phase 3b regression: initial_request stored as plaintext on disk"
            assert decoded.startswith(
                "gAAAAA"
            ), f"Phase 3b regression: ciphertext doesn't have Fernet version prefix; got {decoded[:20]!r}"

            # ---------- (2)+(6)+(7) audit drain to audit_logs ---------------
            deadline = asyncio.get_event_loop().time() + 5.0
            pre = post = []
            while asyncio.get_event_loop().time() < deadline:
                async with get_db_session() as session:
                    rows = (
                        (
                            await session.execute(
                                select(AuditLog).where(AuditLog.user_id == "e2e-baseline-user")
                            )
                        )
                        .scalars()
                        .all()
                    )
                pre = [r for r in rows if r.event_type == "PHI_ACCESS_REQUESTED"]
                post = [r for r in rows if r.event_type == "PHI_ACCESS_COMPLETED"]
                if pre and post:
                    break
                await asyncio.sleep(0.1)

            assert pre, "Phase 2.2 regression: PHI_ACCESS_REQUESTED row missing"
            assert post, "Phase 2.2 regression: PHI_ACCESS_COMPLETED row missing"

            # (3) Phase 1.1: JWT principal flowed into the audit row
            assert pre[0].user_id == "e2e-baseline-user"
            # Phase 2.2 post-event captures the response status code
            assert post[0].status_code == 200

            # (8) Negative tracer: malformed body → 422 with `input` stripped
            bad_response = await client.post(
                "/research/submit",
                json={
                    # missing required fields + oversize initial_request
                    "researcher_name": "x",
                    "initial_request": "Y",
                    "irb_number": "not-a-real-irb-format",
                },
                headers={"authorization": f"Bearer {token}"},
            )
            assert (
                bad_response.status_code == 422
            ), f"Phase 2.3 regression: malformed body should be 422, got {bad_response.status_code}"
            err = bad_response.json()
            for detail in err.get("detail", []):
                assert (
                    "input" not in detail
                ), "Phase 2.3 regression: PHI-safe handler must strip `input` from 422 response"
                assert (
                    "url" not in detail
                ), "Phase 2.3 regression: PHI-safe handler must strip `url` from 422 response"
                assert (
                    "ctx" not in detail
                ), "Phase 2.3 regression: PHI-safe handler must strip `ctx` from 422 response"
