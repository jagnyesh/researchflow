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


REVIEW_NODES = [
    ("_handle_requirements_review", "requirements"),
    ("_handle_phenotype_review", "phenotype_sql"),
    ("_handle_preview_qa_review", "preview_qa"),
    ("_handle_qa_review", "delivery"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [True, False])
@pytest.mark.parametrize("node, approval_type", REVIEW_NODES)
async def test_every_review_gate_records_the_flags_decision(monkeypatch, flag, node, approval_type):
    # The stub run above never enters requirements or preview-QA review; this
    # calls each gate's node directly.
    import uuid

    from app.langchain_orchestrator.langgraph_workflow import FullWorkflow

    monkeypatch.setenv("AUTO_APPROVE_FOR_DEV", "true" if flag else "")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    await init_db()
    request_id = f"REQ-210-{uuid.uuid4().hex[:8].upper()}"
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="Synthetic Researcher",
                researcher_email="r210@example.test",
                initial_request="synthetic",
                current_state="new_request",
            )
        )
    workflow = FullWorkflow(use_real_agents=False)
    state = {
        "request_id": request_id,
        "requirements": {},
        "phenotype_sql": "SELECT 1",
        "estimated_cohort_size": 1,
        "feasibility_score": 1.0,
        "preview_qa_report": {},
        "qa_report": {},
        "extracted_data_summary": {},
    }

    await getattr(workflow, node)(state)

    async with get_db_session() as session:
        [row] = (
            (await session.execute(select(Approval).where(Approval.request_id == request_id)))
            .scalars()
            .all()
        )
    assert row.approval_type == approval_type
    if flag:
        assert (row.status, row.reviewed_by) == ("approved", "auto_approve_for_dev")
    else:
        assert (row.status, row.reviewed_by) == ("pending", None)


ROUTERS = [
    ("_route_after_requirements_review", {"requirements_approved": None}),
    ("_route_after_phenotype_review", {"phenotype_approved": None}),
    ("_route_after_preview_qa_review", {"preview_qa_review_approved": None}),
    ("_route_after_qa_review", {"qa_approved": None}),
]


@pytest.mark.parametrize("router, state", ROUTERS)
def test_routers_follow_the_flag_the_workflow_was_built_with(monkeypatch, router, state):
    # One source for the flag: a router that re-read the env after __init__
    # could wait at a gate whose row was already written as approved.
    from app.langchain_orchestrator.langgraph_workflow import FullWorkflow

    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("AUTO_APPROVE_FOR_DEV", "true")
    auto = FullWorkflow(use_real_agents=False)
    monkeypatch.delenv("AUTO_APPROVE_FOR_DEV")
    manual = FullWorkflow(use_real_agents=False)
    monkeypatch.setenv("AUTO_APPROVE_FOR_DEV", "true")

    assert getattr(auto, router)(dict(state)) != "wait_for_approval"
    assert getattr(manual, router)(dict(state)) == "wait_for_approval"
