"""A reviewer's decision drives the gate's router on resume (#229).

`interrupt_after` pauses once a review node's conditional edge has already
been evaluated on a pending decision, so resuming with `None` followed that
stale edge: a reject resumed onto the approve branch. Drives the real
`LangGraphRequestFacade` -> `FullWorkflow` (stub agents) with the production
`AsyncSqliteSaver` checkpointer on an isolated file and the real SQLite app DB.
The only doubles are the stub agents and a spy that records which nodes ran.

A decision is recorded at most once, and only on the approval its gate is
waiting on (#231); anything else is refused before the DB or the graph changes.
"""

import asyncio
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select

import app.langchain_orchestrator.langgraph_workflow as langgraph_workflow
from app.api import approvals as approvals_api
from app.database import get_db_session, init_db
from app.database.models import Approval
from app.langchain_orchestrator.langgraph_workflow import FullWorkflow
from app.langchain_orchestrator.request_facade import ApprovalRefused, LangGraphRequestFacade
from app.services.approval_service import ApprovalService

pytestmark = [pytest.mark.workflow, pytest.mark.approval]

RESEARCHER = {"name": "Test Researcher", "email": "researcher@example.test"}
REVIEWER = "reviewer@example.test"


@pytest.fixture
async def saver(tmp_path):
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as s:
        yield s


@pytest.fixture
async def facade(saver, monkeypatch):
    monkeypatch.delenv("AUTO_APPROVE_FOR_DEV", raising=False)
    await init_db()
    f = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)
    await f._ensure_initialized()

    async def checkpointer():
        return saver

    f.checkpointer_factory = checkpointer
    return f


@pytest.fixture
def ran(monkeypatch):
    """Every graph node that executes, in order."""
    path = []
    for attr in [a for a in vars(FullWorkflow) if a.startswith("_handle_")]:
        handler = getattr(FullWorkflow, attr)

        async def spy(self, state, _handler=handler, _node=attr.removeprefix("_handle_")):
            path.append(_node)
            return await _handler(self, state)

        monkeypatch.setattr(FullWorkflow, attr, spy)
    return path


def _force_preview_qa_failure(monkeypatch):
    original = FullWorkflow._handle_preview_qa

    async def failing(self, state):
        state = await original(self, state)
        state["preview_qa_passed"] = False
        return state

    monkeypatch.setattr(FullWorkflow, "_handle_preview_qa", failing)


async def _approvals(request_id, approval_type):
    async with get_db_session() as session:
        rows = await session.execute(
            select(Approval.id, Approval.status)
            .where(Approval.request_id == request_id, Approval.approval_type == approval_type)
            .order_by(Approval.id)
        )
        return rows.all()


async def _review(approval_id):
    async with get_db_session() as session:
        approval = await session.get(Approval, approval_id)
        return approval.status, approval.reviewed_by, approval.review_notes


async def _decide(facade, request_id, approval_type, decision, **kwargs):
    pending = [a for a in await _approvals(request_id, approval_type) if a.status == "pending"]
    assert len(pending) == 1, f"expected one pending {approval_type} approval, got {pending}"
    await facade.process_approval_response(pending[0].id, REVIEWER, decision, **kwargs)


async def _snapshot(saver, request_id):
    workflow = FullWorkflow(use_real_agents=False, checkpointer=saver)
    return await workflow.compiled_graph.aget_state({"configurable": {"thread_id": request_id}})


async def _assert_waiting_at(saver, request_id, node):
    """Paused at `node` with nothing scheduled, so a resume without a decision runs nothing."""
    snapshot = await _snapshot(saver, request_id)
    assert snapshot.values["current_state"] == node
    assert snapshot.next == ()


# approval_type -> review node the graph pauses after
GATES = {
    "requirements": "requirements_review",
    "phenotype_sql": "phenotype_review",
    "preview_qa": "preview_qa_review",
    "delivery": "qa_review",
}


async def _pause_at(facade, saver, ran, monkeypatch, approval_type):
    if approval_type == "preview_qa":
        _force_preview_qa_failure(monkeypatch)
    request_id = await facade.process_new_request(
        "Synthetic test request",
        RESEARCHER,
        from_formal_portal=approval_type != "requirements",
    )
    if approval_type in ("preview_qa", "delivery"):
        await _decide(facade, request_id, "phenotype_sql", "approve")
    await _assert_waiting_at(saver, request_id, GATES[approval_type])
    assert [a.status for a in await _approvals(request_id, approval_type)] == ["pending"]
    ran.clear()
    return request_id


async def test_reject_at_phenotype_review_does_not_run_preview_extraction(
    facade, saver, ran, monkeypatch
):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "phenotype_sql")

    await _decide(facade, request_id, "phenotype_sql", "reject", notes="Wrong inclusion criteria")

    assert "preview_extraction" not in ran
    assert ran == ["feasibility_validation", "phenotype_review"]
    assert (await _snapshot(saver, request_id)).values["preview_extracted"] is False
    # the revised SQL is back in front of a reviewer, not stranded
    await _assert_waiting_at(saver, request_id, "phenotype_review")
    assert [a.status for a in await _approvals(request_id, "phenotype_sql")] == [
        "rejected",
        "pending",
    ]


@pytest.mark.parametrize(
    "approval_type, notes, expected_path, reopened_gate",
    [
        (
            "requirements",
            "Missing exclusion criteria",
            ["requirements_gathering", "requirements_review"],
            "requirements",
        ),
        (
            "phenotype_sql",
            "Wrong inclusion criteria",
            ["feasibility_validation", "phenotype_review"],
            "phenotype_sql",
        ),
        ("phenotype_sql", "Not feasible: cohort too small", ["not_feasible"], None),
        (
            "preview_qa",
            "Cohort mismatch, revise SQL",
            ["feasibility_validation", "phenotype_review"],
            "phenotype_sql",
        ),
        ("delivery", "Re-extract", ["data_extraction", "qa_validation", "qa_review"], "delivery"),
    ],
)
async def test_reject_takes_the_reject_branch(
    facade, saver, ran, monkeypatch, approval_type, notes, expected_path, reopened_gate
):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, approval_type)

    await _decide(facade, request_id, approval_type, "reject", notes=notes)

    assert ran == expected_path
    if reopened_gate:
        statuses = [a.status for a in await _approvals(request_id, reopened_gate)]
        assert statuses[-1] == "pending", f"{reopened_gate} gate not re-opened: {statuses}"
        await _assert_waiting_at(saver, request_id, GATES[reopened_gate])


@pytest.mark.parametrize(
    "approval_type, expected_path",
    [
        ("requirements", ["feasibility_validation", "phenotype_review"]),
        (
            "phenotype_sql",
            ["preview_extraction", "preview_qa", "data_extraction", "qa_validation", "qa_review"],
        ),
        # pending used to default to the revise branch here, discarding an approval
        ("preview_qa", ["data_extraction", "qa_validation", "qa_review"]),
        ("delivery", ["data_delivery", "complete"]),
    ],
)
async def test_approve_takes_the_approve_branch(
    facade, saver, ran, monkeypatch, approval_type, expected_path
):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, approval_type)

    await _decide(facade, request_id, approval_type, "approve")

    assert ran == expected_path


@pytest.mark.parametrize("approval_type", GATES)
async def test_resume_without_a_decision_runs_nothing(
    facade, saver, ran, monkeypatch, approval_type
):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, approval_type)
    (pending,) = await _approvals(request_id, approval_type)
    workflow = FullWorkflow(use_real_agents=False, checkpointer=saver)
    config = {"configurable": {"thread_id": request_id}}

    assert await workflow.apply_approval_decision(config, pending.id) is False
    await workflow.compiled_graph.ainvoke(None, config)

    assert ran == []


async def test_a_superseded_approval_cannot_be_re_decided(facade, saver, ran, monkeypatch):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "phenotype_sql")
    await _decide(facade, request_id, "phenotype_sql", "reject", notes="Wrong inclusion criteria")
    superseded = (await _approvals(request_id, "phenotype_sql"))[0]
    ran.clear()

    with pytest.raises(ApprovalRefused, match="already rejected"):
        await facade.process_approval_response(
            superseded.id, "other@example.test", "approve", notes="Looks fine"
        )

    assert ran == []
    await _assert_waiting_at(saver, request_id, "phenotype_review")
    assert await _review(superseded.id) == ("rejected", REVIEWER, "Wrong inclusion criteria")


async def test_superseded_decision_never_resumes_on_the_current_approval(
    facade, saver, ran, monkeypatch
):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "phenotype_sql")
    await _decide(facade, request_id, "phenotype_sql", "reject", notes="Wrong inclusion criteria")
    superseded, current = await _approvals(request_id, "phenotype_sql")
    # reviewer A's decision on the current approval is committed; A's resume has not run yet
    await facade.approval_bridge.update_approval_status(current.id, "approved", REVIEWER)
    ran.clear()

    with pytest.raises(ApprovalRefused):
        await facade.process_approval_response(superseded.id, "other@example.test", "approve")

    assert ran == []


async def test_decision_from_another_request_is_refused(facade, saver, ran, monkeypatch):
    waiting = await _pause_at(facade, saver, ran, monkeypatch, "phenotype_sql")
    other = await _pause_at(facade, saver, ran, monkeypatch, "phenotype_sql")
    (other_approval,) = await _approvals(other, "phenotype_sql")
    await facade.approval_bridge.update_approval_status(other_approval.id, "approved", REVIEWER)
    workflow = FullWorkflow(use_real_agents=False, checkpointer=saver)
    config = {"configurable": {"thread_id": waiting}}

    assert await workflow.apply_approval_decision(config, other_approval.id) is False
    await _assert_waiting_at(saver, waiting, "phenotype_review")


async def test_preview_qa_gate_reopens_after_a_second_failure(facade, saver, ran, monkeypatch):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "preview_qa")
    await _decide(facade, request_id, "preview_qa", "reject", notes="Cohort mismatch, revise SQL")
    ran.clear()

    await _decide(facade, request_id, "phenotype_sql", "approve")

    assert ran == ["preview_extraction", "preview_qa", "preview_qa_review"]
    assert [a.status for a in await _approvals(request_id, "preview_qa")] == [
        "rejected",
        "pending",
    ]
    await _assert_waiting_at(saver, request_id, "preview_qa_review")


async def test_gate_routes_on_the_decided_approval_when_the_clock_steps_back(
    facade, saver, ran, monkeypatch
):
    # phenotype approval #1 approved; a preview-QA reject re-opens the gate as #2
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "preview_qa")
    await _decide(facade, request_id, "preview_qa", "reject", notes="Cohort mismatch, revise SQL")
    approved, reopened = await _approvals(request_id, "phenotype_sql")
    async with get_db_session() as session:
        # created_at is naive local time: a DST fall-back or NTP step orders it backwards
        first = await session.get(Approval, approved.id)
        (await session.get(Approval, reopened.id)).created_at = first.created_at - timedelta(
            hours=1
        )
        await session.commit()
    ran.clear()

    await _decide(facade, request_id, "phenotype_sql", "reject", notes="Still wrong")

    assert ran == ["feasibility_validation", "phenotype_review"]


async def test_thread_paused_before_the_fix_routes_on_the_decision(facade, saver, ran):
    current = FullWorkflow._route_after_phenotype_review

    def pre_229_router(self, state):
        route = current(self, state)
        return "preview_extraction" if route == "wait_for_approval" else route

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(FullWorkflow, "_route_after_phenotype_review", pre_229_router)
        request_id = await facade.process_new_request(
            "Synthetic test request", RESEARCHER, from_formal_portal=True
        )
    assert (await _snapshot(saver, request_id)).next == ("preview_extraction",)
    ran.clear()

    await _decide(facade, request_id, "phenotype_sql", "reject", notes="Wrong inclusion criteria")

    assert ran == ["feasibility_validation", "phenotype_review"]
    await _assert_waiting_at(saver, request_id, "phenotype_review")


async def test_repeating_an_earlier_gate_decision_does_not_rewind_the_graph(
    facade, saver, ran, monkeypatch
):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "delivery")
    (phenotype,) = await _approvals(request_id, "phenotype_sql")

    with pytest.raises(ApprovalRefused):
        await facade.process_approval_response(phenotype.id, REVIEWER, "approve")

    assert ran == []
    await _assert_waiting_at(saver, request_id, "qa_review")


async def test_reviewer_modified_sql_reaches_the_graph(facade, saver, ran, monkeypatch):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "phenotype_sql")
    reviewed_sql = "SELECT patient_id FROM sqlonfhir.patient_demographics -- reviewer edit"

    await _decide(
        facade, request_id, "phenotype_sql", "modify", modifications={"phenotype_sql": reviewed_sql}
    )

    assert ran[0] == "preview_extraction"
    assert (await _snapshot(saver, request_id)).values["phenotype_sql"] == reviewed_sql


async def test_unknown_decision_is_refused_and_records_nothing(facade, saver, ran, monkeypatch):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "phenotype_sql")

    with pytest.raises(ValueError, match="Unknown decision"):
        await _decide(facade, request_id, "phenotype_sql", "rejected")

    assert ran == []
    assert [a.status for a in await _approvals(request_id, "phenotype_sql")] == ["pending"]
    await _assert_waiting_at(saver, request_id, "phenotype_review")


async def test_deciding_a_missing_approval_is_refused(facade):
    with pytest.raises(ApprovalRefused, match="not found"):
        await facade.process_approval_response(10**9, REVIEWER, "approve")


async def test_the_bridge_never_overwrites_a_decided_approval(facade, saver, ran, monkeypatch):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "phenotype_sql")
    await _decide(facade, request_id, "phenotype_sql", "reject", notes="Wrong inclusion criteria")
    rejected = (await _approvals(request_id, "phenotype_sql"))[0]

    recorded = await facade.approval_bridge.update_approval_status(
        rejected.id, "approved", "other@example.test", "Looks fine"
    )

    assert recorded is False
    assert await _review(rejected.id) == ("rejected", REVIEWER, "Wrong inclusion criteria")


@pytest.mark.parametrize("second", ["approve", "reject"])
async def test_concurrent_decisions_resume_the_graph_once(facade, saver, ran, monkeypatch, second):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "delivery")
    (pending,) = await _approvals(request_id, "delivery")
    deliver = FullWorkflow._handle_data_delivery

    async def slow_delivery(self, state):
        # keeps the first resume in flight while the second decision lands
        await asyncio.sleep(0.3)
        return await deliver(self, state)

    monkeypatch.setattr(FullWorkflow, "_handle_data_delivery", slow_delivery)

    outcomes = await asyncio.gather(
        facade.process_approval_response(pending.id, REVIEWER, "approve"),
        facade.process_approval_response(pending.id, "other@example.test", second),
        return_exceptions=True,
    )

    assert sorted(type(o).__name__ for o in outcomes) == ["ApprovalRefused", "NoneType"], outcomes
    statuses = [a.status for a in await _approvals(request_id, "delivery")]
    if statuses[0] == "approved":
        assert ran == ["data_delivery", "complete"]
    else:
        assert ran == ["data_extraction", "qa_validation", "qa_review"]
        assert statuses == ["rejected", "pending"]


async def test_a_decision_before_the_gate_is_checkpointed_stays_pending_for_a_retry(
    facade, saver, ran, monkeypatch
):
    create = langgraph_workflow.create_approval_from_state
    early = []

    async def create_then_decide(request_id, approval_type, state, **kwargs):
        # the reviewer decides after the pending row commits, before the graph pauses
        approval_id = await create(request_id, approval_type, state, **kwargs)
        try:
            early.append(await facade.process_approval_response(approval_id, REVIEWER, "approve"))
        except ApprovalRefused as refused:
            early.append(refused)
        return approval_id

    monkeypatch.setattr(langgraph_workflow, "create_approval_from_state", create_then_decide)
    request_id = await facade.process_new_request(
        "Synthetic test request", RESEARCHER, from_formal_portal=True
    )
    monkeypatch.setattr(langgraph_workflow, "create_approval_from_state", create)

    assert [type(e) for e in early] == [ApprovalRefused]
    assert [a.status for a in await _approvals(request_id, "phenotype_sql")] == ["pending"]
    await _assert_waiting_at(saver, request_id, "phenotype_review")
    ran.clear()

    await _decide(facade, request_id, "phenotype_sql", "approve")

    assert ran[0] == "preview_extraction"


async def test_deleting_the_current_approval_does_not_revive_the_superseded_one(
    facade, saver, ran, monkeypatch
):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "phenotype_sql")
    await _decide(facade, request_id, "phenotype_sql", "reject", notes="Wrong inclusion criteria")
    superseded, current = await _approvals(request_id, "phenotype_sql")
    async with get_db_session() as session:
        # out of band: no app or script path deletes approvals
        await session.delete(await session.get(Approval, current.id))
        await session.commit()
    ran.clear()

    with pytest.raises(ApprovalRefused):
        await facade.process_approval_response(superseded.id, REVIEWER, "approve")

    assert ran == []


async def test_an_approval_with_no_gate_is_recorded_without_moving_the_graph(
    facade, saver, ran, monkeypatch
):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "phenotype_sql")
    async with get_db_session() as session:
        scope = await ApprovalService(session).create_approval(
            request_id, "scope_change", "researcher@example.test", {"requested_changes": {}}
        )

    await facade.process_approval_response(scope.id, REVIEWER, "approve")

    assert ran == []
    assert await _review(scope.id) == ("approved", REVIEWER, None)
    await _assert_waiting_at(saver, request_id, "phenotype_review")
    with pytest.raises(ApprovalRefused, match="already approved"):
        await facade.process_approval_response(scope.id, REVIEWER, "reject")


async def test_the_api_reports_a_refused_decision(facade, saver, ran, monkeypatch):
    request_id = await _pause_at(facade, saver, ran, monkeypatch, "phenotype_sql")
    (pending,) = await _approvals(request_id, "phenotype_sql")
    api = FastAPI()
    api.include_router(approvals_api.router)
    monkeypatch.setattr(approvals_api, "orchestrator", facade)
    body = {"decision": "approve", "reviewer": REVIEWER}

    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(f"/approvals/{pending.id}/respond", json=body)
        repeat = await client.post(f"/approvals/{pending.id}/respond", json=body)

    assert first.status_code == 200, first.text
    assert repeat.status_code == 400, repeat.text
    assert "already approved" in repeat.json()["detail"]
