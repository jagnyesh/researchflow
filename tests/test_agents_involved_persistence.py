"""#323: a workflow failure's agents_involved entry survives a reload.

agents_involved is a plain JSON column. Appending to the loaded list in place
and assigning the same object back is never marked dirty, so the entry was
never written once the list already held one. Real facade (stub agents, no
LLM) and the real (test) database.
"""

import pytest
from sqlalchemy import select

from app.database import ResearchRequest, get_db_session, init_db
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade

RESEARCHER = {"name": "Dr. Synthetic", "email": "s@example.org"}


@pytest.fixture
async def failing_facade():
    f = LangGraphRequestFacade(use_real_agents=False)
    await f._ensure_initialized()  # it resets checkpointer_factory

    async def checkpointer():
        raise RuntimeError("synthetic workflow failure")

    f.checkpointer_factory = checkpointer
    yield f
    await f.close()


async def _agents_involved(request_id: str) -> list:
    async with get_db_session() as session:
        req = (
            await session.execute(select(ResearchRequest).where(ResearchRequest.id == request_id))
        ).scalar_one()
        return req.agents_involved


@pytest.mark.asyncio
async def test_each_workflow_failure_is_recorded_in_agents_involved(failing_facade):
    await init_db()
    request_id = await failing_facade.process_new_request("synthetic request", RESEARCHER)
    await failing_facade._run_workflow(request_id, "synthetic request", RESEARCHER)

    entries = await _agents_involved(request_id)

    assert [(e["agent"], e["error_type"]) for e in entries] == [
        ("langgraph_workflow", "RuntimeError"),
        ("langgraph_workflow", "RuntimeError"),
    ]
