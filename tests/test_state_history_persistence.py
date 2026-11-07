"""#63: research_requests.state_history records every workflow transition.

It stayed at its creation entry: the sync compared the new state after
overwriting it, and in-place appends to a plain JSON column were never marked
dirty. Real facade (stub agents, no LLM) and the real (test) database.
"""

import uuid

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select

from app.database import ResearchRequest, get_db_session, init_db
from app.langchain_orchestrator.request_facade import (
    LangGraphRequestFacade,
    record_state_transition,
)


@pytest.fixture(autouse=True)
def _delivery_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DELIVERY_PATH", str(tmp_path))


@pytest.fixture
async def facade(tmp_path):
    # A per-test saver, closed with the test: the default checkpointer is a
    # process-wide aiosqlite connection whose non-daemon thread keeps pytest
    # from exiting.
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        f = LangGraphRequestFacade(use_real_agents=False)
        await f._ensure_initialized()  # it resets checkpointer_factory

        async def checkpointer():
            return saver

        f.checkpointer_factory = checkpointer
        yield f
        await f.close()


async def _history(request_id: str) -> list:
    async with get_db_session() as session:
        req = (
            await session.execute(select(ResearchRequest).where(ResearchRequest.id == request_id))
        ).scalar_one()
        return [entry["state"] for entry in req.state_history]


@pytest.mark.asyncio
async def test_a_request_records_each_state_it_passes_through(facade):
    await init_db()
    request_id = await facade.process_new_request(
        "female patients over 50 with diabetes", {"name": "Dr. Synthetic", "email": "s@example.org"}
    )
    async with get_db_session() as session:
        from app.database.models import Approval

        gate = (
            await session.execute(select(Approval).where(Approval.request_id == request_id))
        ).scalar_one()
    await facade.process_approval_response(gate.id, "reviewer@example.org", "approve")

    history = await _history(request_id)

    assert history[0] == "new_request"
    assert "requirements_review" in history
    assert history[-1] == "phenotype_review"
    assert history.index("requirements_review") < history.index("phenotype_review")


@pytest.mark.asyncio
async def test_recording_the_same_state_twice_adds_one_entry():
    await init_db()
    rid = f"REQ-SH-{uuid.uuid4().hex[:8]}"
    async with get_db_session() as session:
        req = ResearchRequest(
            id=rid,
            researcher_name="Synthetic",
            researcher_email="s@example.org",
            initial_request="synthetic",
            current_state="new_request",
            state_history=[{"state": "new_request", "timestamp": "2026-11-04T00:00:00"}],
        )
        session.add(req)
    async with get_db_session() as session:
        req = (
            await session.execute(select(ResearchRequest).where(ResearchRequest.id == rid))
        ).scalar_one()
        record_state_transition(req, "requirements_review")
        record_state_transition(req, "requirements_review")

    assert await _history(rid) == ["new_request", "requirements_review"]


@pytest.mark.asyncio
async def test_a_repeat_carrying_details_is_still_recorded():
    # e.g. the dashboard's preview approval: its approved_by/notes must not be
    # dropped just because the last entry already names the same state.
    await init_db()
    rid = f"REQ-SH-{uuid.uuid4().hex[:8]}"
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=rid,
                researcher_name="Synthetic",
                researcher_email="s@example.org",
                initial_request="synthetic",
                current_state="data_extraction",
                state_history=[{"state": "data_extraction", "timestamp": "2026-11-04T00:00:00"}],
            )
        )
    async with get_db_session() as session:
        req = (
            await session.execute(select(ResearchRequest).where(ResearchRequest.id == rid))
        ).scalar_one()
        record_state_transition(req, "data_extraction", approved_by="admin_dashboard")

    assert await _history(rid) == ["data_extraction", "data_extraction"]
