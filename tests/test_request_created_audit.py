"""#267: request_created audit rows record ids, not PHI-bearing text.

event_data is a plain JSON column; the researcher's name and the request text
already live on the (encrypted where needed) request row the entry points to.
Drives the real facade (stub agents) against the real SQLite app DB.
"""

import json

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select

from app.database import get_db_session, init_db
from app.database.models import AuditLog
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade

NAME = "Synthetic Researcher Name-267"
REQUEST_TEXT = "Synthetic request text 267 about diabetic patients"


@pytest.fixture
async def facade(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTO_APPROVE_FOR_DEV", raising=False)
    await init_db()
    f = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)
    await f._ensure_initialized()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.db")) as saver:

        async def checkpointer():
            return saver

        f.checkpointer_factory = checkpointer
        yield f


@pytest.mark.asyncio
@pytest.mark.parametrize("formal", [True, False])
async def test_request_created_event_data_holds_no_name_or_request_text(facade, formal):
    request_id = await facade.process_new_request(
        REQUEST_TEXT, {"name": NAME, "email": "r267@example.test"}, from_formal_portal=formal
    )

    async with get_db_session() as session:
        row = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.request_id == request_id, AuditLog.event_type == "request_created"
                )
            )
        ).scalar_one()

    assert set(row.event_data) == {"orchestrator", "source"}
    assert row.event_data["source"] == ("formal" if formal else "exploratory")
    dumped = json.dumps(row.event_data)
    assert NAME not in dumped and REQUEST_TEXT not in dumped and "r267@" not in dumped
