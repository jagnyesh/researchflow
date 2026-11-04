"""#224: PHI_ACCESS_COMPLETED records the outcome after the body is sent.

#180's backstop only covered exceptions raised before the response started.
A body that failed mid-stream sent a truncated 200, the audit trail said
COMPLETED(200), and the server logged the exception message. Decided
2026-11-04 (ADR 0032): the middleware writes COMPLETED after the body with
the real outcome; a failed post-write after the body is logged, since the
503 can no longer be sent.

uvicorn's own "Exception in ASGI application" line is not captured
in-process. The middleware re-raises a PHI-safe exception with its context
suppressed, so that line can only carry the type and ref.
"""

import json
import logging
import re
from pathlib import Path

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from httpx import ASGITransport, AsyncClient

PHI_NEEDLE = "patient QQ-7731 eGFR 41 on 2026-03-09"
seen_mid_stream = []


@pytest.fixture
async def queue():
    from app.security import audit_middleware as am

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(client)
    yield client
    am.set_audit_redis(previous)
    await client.aclose()


@pytest.fixture
def app(tmp_path):
    from app.security import audit_middleware as am

    app = FastAPI()
    am.install_audit_middleware(app)
    export = tmp_path / "export.csv"
    export.write_text("id,count\n1,12\n")

    @app.get("/research/zz_stream_fails")
    async def stream_fails():
        async def rows():
            yield b"id,count\n"
            raise OSError(PHI_NEEDLE)

        return StreamingResponse(rows(), media_type="text/csv")

    @app.get("/research/zz_stream_ok")
    async def stream_ok():
        async def rows():
            yield b"id,count\n"
            seen_mid_stream.append(await _event_types(am._audit_redis, keep=True))
            yield b"1,12\n"

        return StreamingResponse(rows(), media_type="text/csv")

    @app.get("/research/zz_file")
    async def file_download():
        return FileResponse(Path(export))

    return app


def _token():
    from datetime import timedelta

    from app.security.auth import create_access_token

    return create_access_token(
        {"sub": "u@example.org", "user_id": "USR-224", "role": "researcher"},
        expires_delta=timedelta(minutes=5),
    )


async def _event_types(queue, keep=False):
    from app.security import audit_middleware as am

    items = await queue.lrange(am.AUDIT_QUEUE_KEY, 0, -1)
    if not keep:
        await queue.delete(am.AUDIT_QUEUE_KEY)
    return [(e["event_type"], e["status_code"]) for e in map(json.loads, items)]


async def _get(app, path, caplog):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, headers={"authorization": f"Bearer {_token()}"})


@pytest.mark.asyncio
async def test_a_body_that_fails_mid_stream_is_audited_as_failed(queue, app, caplog):
    try:
        await _get(app, "/research/zz_stream_fails", caplog)
    except Exception as exc:  # the transport may surface the aborted stream
        assert PHI_NEEDLE not in str(exc)

    events = await _event_types(queue)
    assert events == [("PHI_ACCESS_REQUESTED", None), ("PHI_ACCESS_COMPLETED", 500)]
    assert PHI_NEEDLE not in caplog.text
    assert re.search(r"ref=[0-9a-f]{12}", caplog.text)


@pytest.mark.asyncio
async def test_completed_is_written_only_after_the_whole_body(queue, app, caplog):
    seen_mid_stream.clear()

    response = await _get(app, "/research/zz_stream_ok", caplog)

    assert response.text == "id,count\n1,12\n"
    assert seen_mid_stream == [[("PHI_ACCESS_REQUESTED", None)]]
    assert await _event_types(queue) == [
        ("PHI_ACCESS_REQUESTED", None),
        ("PHI_ACCESS_COMPLETED", 200),
    ]


@pytest.mark.asyncio
async def test_a_file_download_still_completes_with_200(queue, app, caplog):
    response = await _get(app, "/research/zz_file", caplog)

    assert response.status_code == 200 and response.text == "id,count\n1,12\n"
    assert await _event_types(queue) == [
        ("PHI_ACCESS_REQUESTED", None),
        ("PHI_ACCESS_COMPLETED", 200),
    ]


@pytest.mark.asyncio
async def test_a_lost_post_event_after_the_body_is_logged(queue, app, caplog, monkeypatch):
    from app.security import audit_middleware as am

    real = am._try_enqueue

    async def fail_completed(payload):
        if payload["event_type"] == "PHI_ACCESS_COMPLETED":
            return False
        return await real(payload)

    monkeypatch.setattr(am, "_try_enqueue", fail_completed)

    response = await _get(app, "/research/zz_stream_ok", caplog)

    assert response.status_code == 200  # headers were sent before the write failed
    assert "PHI_ACCESS_COMPLETED not recorded" in caplog.text


def test_no_api_route_runs_background_tasks():
    # A BackgroundTasks task runs after the response, outside the audited body;
    # none exists today, and a new one needs the same treatment first (ADR 0032).
    root = Path(__file__).resolve().parents[1] / "app"
    users = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if "BackgroundTasks" in p.read_text() or ".add_task(" in p.read_text()
    ]
    assert users == []


def test_the_app_runs_the_guard_inside_the_audit_middleware():
    from app.main import app
    from app.security import audit_middleware as am

    # user_middleware lists outermost first.
    stack = [
        getattr(m.kwargs.get("dispatch"), "__name__", None) or m.cls.__name__
        for m in app.user_middleware
    ]
    assert stack.index("AuditBodyGuard") == stack.index("audit_middleware") + 1, stack
    assert am.AuditBodyGuard.__name__ in stack
