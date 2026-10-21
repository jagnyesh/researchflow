"""PHI-safe API error paths (#175, ADR 0029).

A SQLAlchemy StatementError's str() carries the failed statement's bound
parameters, so `detail=str(e)` on a failed write echoed researcher PII (and the
PHI `initial_request` column) to the client and the log. These tests pin the
contract at the wire: no exception text in responses or logs, a correlating
ref in both, and the audit REQUESTED/COMPLETED pair intact on a 500.
"""

import ast
import json
import logging
import os
import re
from datetime import timedelta
from pathlib import Path

import fakeredis.aioredis
import pytest

os.environ.setdefault("ENABLE_ORCHESTRATOR", "false")

PHI_NEEDLE = "patient ZZ-9917 HbA1c 11.4 on 2026-01-02"
EMAIL_NEEDLE = "leak-canary@example.org"
IRB_NEEDLE = "IRB-2099-4242"


@pytest.fixture
async def fake_audit_redis():
    from app.security import audit_middleware as am

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = am._audit_redis
    am.set_audit_redis(client)
    yield client
    am.set_audit_redis(previous)
    await client.aclose()


def test_internal_error_logs_and_returns_no_exception_text(caplog):
    from fastapi import HTTPException

    from app.schemas._errors import internal_error

    log = logging.getLogger("tests.api_error_leak")
    try:
        try:
            raise KeyError(PHI_NEEDLE)
        except KeyError as inner:
            raise RuntimeError(f"wrapped: {EMAIL_NEEDLE}") from inner
    except RuntimeError as e:
        with caplog.at_level(logging.ERROR, logger="tests.api_error_leak"):
            exc = internal_error(log, "doing the thing", e)

    assert isinstance(exc, HTTPException)
    assert exc.status_code == 500
    ref = re.search(r"ref: ([0-9a-f]{12})\)$", exc.detail).group(1)

    logged = caplog.text
    for needle in (PHI_NEEDLE, EMAIL_NEEDLE):
        assert needle not in exc.detail
        assert needle not in logged
    assert ref in logged
    assert "RuntimeError" in logged and "KeyError" in logged  # type chain kept
    assert "doing the thing" in logged


@pytest.mark.asyncio
async def test_submit_db_failure_leaks_nothing_and_keeps_audit_pair(
    fake_audit_redis, monkeypatch, caplog
):
    """The observed #175 path: a failing INSERT on /research/submit."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.security import audit_middleware as am
    from app.security.auth import create_access_token

    # The EncryptedText column resolves its key at bind time; removing it makes
    # the INSERT raise a StatementError whose str() embeds every bound param.
    monkeypatch.delenv("ENCRYPTION_KEY_PRIMARY", raising=False)

    token = create_access_token(
        {"sub": EMAIL_NEEDLE, "user_id": "leak-1", "role": "researcher"},
        expires_delta=timedelta(minutes=5),
    )
    body = {
        "researcher_name": "Dr. Canary",
        "researcher_email": EMAIL_NEEDLE,
        "irb_number": IRB_NEEDLE,
        "initial_request": PHI_NEEDLE,
    }
    with caplog.at_level(logging.DEBUG):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/research/submit", json=body, headers={"authorization": f"Bearer {token}"}
            )

    assert response.status_code == 500
    for needle in (PHI_NEEDLE, EMAIL_NEEDLE, IRB_NEEDLE, "INSERT INTO", "parameters"):
        assert needle not in response.text, f"response leaked {needle!r}"
        assert needle not in caplog.text, f"log leaked {needle!r}"

    ref = re.search(r"ref: ([0-9a-f]{12})", response.json()["detail"]).group(1)
    assert ref in caplog.text

    events = []
    while (item := await fake_audit_redis.lpop(am.AUDIT_QUEUE_KEY)) is not None:
        events.append(json.loads(item))
    completed = [e for e in events if e["event_type"] == "PHI_ACCESS_COMPLETED"]
    assert {e["event_type"] for e in events} >= {"PHI_ACCESS_REQUESTED", "PHI_ACCESS_COMPLETED"}
    assert completed[0]["status_code"] == 500


API_DIR = Path(__file__).resolve().parents[1] / "app" / "api"
# helper name -> positional index of its exception argument
_HELPERS = {"internal_error": 2, "log_internal_error": 2, "failure_text": 2}
_BANNED_CALLS = {"format_exc", "print_exc", "format_exception", "exc_info", "exception"}


def _call_name(node: ast.AST):
    """`f` for `f(...)` or `obj.f(...)`; None for anything else."""
    if not isinstance(node, ast.Call):
        return None
    return (
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
    )


def _is_intentional_4xx(node: ast.AST, handler: ast.ExceptHandler) -> bool:
    """The ADR 0029 carve-out: `except ValueError as e: raise HTTPException(
    status_code=4xx, detail=str(e))` — app-authored validation messages."""
    if not (isinstance(handler.type, ast.Name) and handler.type.id == "ValueError"):
        return False
    if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
        return False
    kw = {k.arg: k.value for k in node.exc.keywords}
    status, detail = kw.get("status_code"), kw.get("detail")
    # Exactly `detail=str(e)`: `str(e.__cause__)` or any other expression could
    # carry a wrapped StatementError's bound params.
    return (
        isinstance(status, ast.Constant)
        and isinstance(status.value, int)
        and 400 <= status.value < 500
        and isinstance(detail, ast.Call)
        and isinstance(detail.func, ast.Name)
        and detail.func.id == "str"
        and len(detail.args) == 1
        and isinstance(detail.args[0], ast.Name)
        and detail.args[0].id == handler.name
    )


def _handler_leaks(tree: ast.AST):
    """Yield line numbers where a caught exception escapes other than through
    the PHI-safe helpers or the intentional 4xx carve-out."""
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or handler.name is None:
            continue
        allowed = set()
        for node in ast.walk(handler):
            name = _call_name(node)
            if name in _HELPERS:
                # Only the exception slot (or exc=); `e` as the context string
                # would be str()-ed into the log.
                i = _HELPERS[name]
                slot = node.args[i : i + 1] + [k.value for k in node.keywords if k.arg == "exc"]
                allowed.update(
                    id(a) for a in slot if isinstance(a, ast.Name) and a.id == handler.name
                )
            if (  # type(e) carries no message
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "type"
            ):
                allowed.update(id(a) for a in node.args if isinstance(a, ast.Name))
            if _is_intentional_4xx(node, handler):
                detail = next(k.value for k in node.exc.keywords if k.arg == "detail")
                allowed.add(id(detail.args[0]))  # the `e` in `detail=str(e)`
        for node in ast.walk(handler):
            if (
                isinstance(node, ast.Name)
                and node.id == handler.name
                and isinstance(node.ctx, ast.Load)
                and id(node) not in allowed
            ):
                yield node.lineno


def _banned_calls(tree: ast.AST):
    """traceback.format_exc()/sys.exc_info()/logger.exception()/exc_info= re-emit
    the message without naming the bound exception, so the name check can't see them."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in _BANNED_CALLS:
                yield node.lineno
            if any(k.arg == "exc_info" for k in node.keywords):
                yield node.lineno


def test_no_api_handler_exposes_exception_text():
    """Static guard: re-introducing `detail=str(e)` / `{e}` in app/api fails CI."""
    violations = []
    for path in sorted(API_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        violations += [f"{path.name}:{line}" for line in _handler_leaks(tree)]
        violations += [f"{path.name}:{line} (banned call)" for line in _banned_calls(tree)]
    assert not violations, "exception text escapes a handler at: " + ", ".join(violations)


@pytest.mark.parametrize(
    "src",
    [
        "try:\n    x()\nexcept BaseException as e:\n    log.error(str(e))",
        "try:\n    x()\nexcept (Exception,) as e:\n    y = repr(e)",
        "try:\n    x()\nexcept ValueError as e:\n    raise HTTPException(status_code=500, detail=str(e))",
        "try:\n    x()\nexcept Exception:\n    log.error(traceback.format_exc())",
        "try:\n    x()\nexcept Exception:\n    logger.exception('boom')",
        "try:\n    x()\nexcept ValueError as e:\n"
        "    raise HTTPException(status_code=400, detail=str(e.__cause__))",
        "try:\n    x()\nexcept ValueError as e:\n"
        "    raise HTTPException(status_code=400, detail=log.error(str(e)) or 'x')",
        "try:\n    x()\nexcept Exception as e:\n    raise internal_error(logger, e, e)",
    ],
)
def test_guard_catches_known_bypasses(src):
    tree = ast.parse(src)
    assert list(_handler_leaks(tree)) or list(_banned_calls(tree))


def test_guard_allows_the_4xx_carve_out_and_helpers():
    src = (
        "try:\n    x()\nexcept ValueError as e:\n"
        "    raise HTTPException(status_code=400, detail=str(e))\n"
        "except Exception as e:\n    raise internal_error(logger, 'ctx', e)"
    )
    tree = ast.parse(src)
    assert not list(_handler_leaks(tree)) and not list(_banned_calls(tree))


def test_log_context_cannot_forge_lines(caplog):
    from app.schemas._errors import log_internal_error

    log = logging.getLogger("tests.api_error_leak")
    with caplog.at_level(logging.ERROR, logger="tests.api_error_leak"):
        log_internal_error(log, "Error for id x\nFAKE ERROR line", RuntimeError("m"))
    assert "x\\nFAKE" in caplog.records[0].getMessage()


@pytest.mark.asyncio
async def test_create_all_returns_no_script_output(fake_audit_redis, monkeypatch, caplog):
    """create-all used to return the script's stdout (HAPI_DB_URL credentials,
    asyncpg error text) in a 200 and log raw stderr on failure."""
    import asyncio as _asyncio

    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from app.security.auth import create_access_token

    canary = "postgresql://hapi:SECRET-CANARY@db:5433/hapi"

    class FakeProc:
        def __init__(self, rc):
            self.returncode = rc

        async def communicate(self):
            return (f"Database: {canary}".encode(), f"Traceback: {PHI_NEEDLE}".encode())

    token = create_access_token(
        {"sub": "admin@example.com", "user_id": "admin-1", "role": "admin"},
        expires_delta=timedelta(minutes=5),
    )
    for rc, status in ((0, 200), (1, 500)):

        async def fake_exec(*a, _rc=rc, **k):
            return FakeProc(_rc)

        monkeypatch.setattr(_asyncio, "create_subprocess_exec", fake_exec)
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/analytics/materialized-views/create-all",
                    headers={"authorization": f"Bearer {token}"},
                )
        assert resp.status_code == status, resp.text
        for needle in ("SECRET-CANARY", PHI_NEEDLE):
            assert needle not in resp.text
            assert needle not in caplog.text
