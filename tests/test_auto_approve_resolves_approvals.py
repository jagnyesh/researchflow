"""#210: under AUTO_APPROVE_FOR_DEV no approval row is left pending.

The flag skipped the interrupts but the review nodes still wrote pending
rows, so a delivered request showed its SQL review as never done. Drives
the real facade -> FullWorkflow (stub agents) -> approval rows in the DB.
"""

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select

from app.database import ResearchRequest, get_db_session, init_db
from app.database.models import Approval
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade


async def _run(tmp_path):
    await init_db()
    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)
    await facade._ensure_initialized()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.db")) as saver:

        async def checkpointer():
            return saver

        facade.checkpointer_factory = checkpointer
        request_id = await facade.process_new_request(
            "Synthetic test request",
            {"name": "Test Researcher", "email": "researcher@example.test"},
            from_formal_portal=True,
        )
    async with get_db_session() as session:
        request = await session.get(ResearchRequest, request_id)
        approvals = (
            (await session.execute(select(Approval).where(Approval.request_id == request_id)))
            .scalars()
            .all()
        )
    return request, approvals


@pytest.mark.asyncio
async def test_an_auto_approved_run_leaves_no_pending_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE_FOR_DEV", "true")
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    request, approvals = await _run(tmp_path)

    assert request.current_state in ("complete", "delivered")
    assert approvals, "the review nodes still record each gate"
    assert [a.status for a in approvals if a.status == "pending"] == []
    for a in approvals:
        assert a.status == "approved"
        assert a.reviewed_by == "auto_approve_for_dev"
        assert a.reviewed_at is not None
        assert "AUTO_APPROVE_FOR_DEV" in (a.review_notes or "")


@pytest.mark.asyncio
async def test_without_the_flag_the_first_gate_stays_pending_for_a_human(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTO_APPROVE_FOR_DEV", raising=False)

    request, approvals = await _run(tmp_path)

    assert [(a.approval_type, a.status, a.reviewed_by) for a in approvals] == [
        ("phenotype_sql", "pending", None)
    ]


def test_the_flag_still_refuses_production(monkeypatch):
    from app.langchain_orchestrator.langgraph_workflow import FullWorkflow

    monkeypatch.setenv("AUTO_APPROVE_FOR_DEV", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(RuntimeError, match="AUTO_APPROVE_FOR_DEV"):
        FullWorkflow()
