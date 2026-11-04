"""
Agent handoffs through the LangGraph workflow (#65, ported off the retired A2A FSM).

Kept from the A2A suite (ADR 0024 D3 triage on #65):
- a request pauses at its first approval gate with a pending approval (was
  test_agent_handoff_sequence + test_approval_workflow_handoff);
- approving that gate hands off to the next stage;
- agent executions are tracked (real agents only; needs an API key).

Deleted, with reasons:
- test_audit_log_tracking: asserted 5+ audit events per workflow; the agent
  path fires only request_created (#64). Porting would lock in the gap.
- test_handoff_with_context_passing, test_failed_handoff_handling,
  test_concurrent_handoffs: exercised A2A primitives LangGraph doesn't have
  (state is a FullWorkflowState dict; errors are graph errors; each workflow
  runs sequentially through its StateGraph).
- TestAgentHandoffDiagnostics: printed diagnostics and asserted nothing;
  approval bottlenecks are now measured by app/services/gate_telemetry.py (#144).

Stub mode (use_real_agents=False) is deterministic and makes no LLM calls.
"""

import pytest
from sqlalchemy import select

from app.database import get_db_session, init_db
from app.database.models import AgentExecution, Approval
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade

REQUEST = "I need female patients over 50 with diabetes"
RESEARCHER = {"name": "Dr. Synthetic", "email": "synthetic@example.org", "department": "Research"}


@pytest.fixture(autouse=True)
def _delivery_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DELIVERY_PATH", str(tmp_path))


async def _approvals(request_id: str) -> list:
    async with get_db_session() as session:
        result = await session.execute(select(Approval).where(Approval.request_id == request_id))
        return result.scalars().all()


@pytest.mark.asyncio
async def test_a_new_request_pauses_at_requirements_review_with_its_approval():
    await init_db()
    facade = LangGraphRequestFacade(use_real_agents=False)

    request_id = await facade.process_new_request(REQUEST, RESEARCHER)

    status = await facade.get_request_status(request_id)
    approvals = await _approvals(request_id)
    assert status["current_state"] == "requirements_review"
    assert [(a.approval_type, a.status) for a in approvals] == [("requirements", "pending")]


@pytest.mark.asyncio
async def test_approving_requirements_hands_off_to_phenotype_review():
    await init_db()
    facade = LangGraphRequestFacade(use_real_agents=False)
    request_id = await facade.process_new_request(REQUEST, RESEARCHER)
    (gate,) = await _approvals(request_id)

    await facade.process_approval_response(gate.id, "reviewer@example.org", "approve")

    status = await facade.get_request_status(request_id)
    approvals = {a.approval_type: a.status for a in await _approvals(request_id)}
    # The workflow moves on to the next gate (G2) and opens its approval.
    assert approvals == {"requirements": "approved", "phenotype_sql": "pending"}
    assert status["current_state"] == "phenotype_review"


@pytest.mark.requires_api_key
@pytest.mark.asyncio
async def test_real_agent_executions_are_tracked():
    # Execution rows are written only on the real-agent path; that needs a live
    # LLM, so this runs only where an API key is configured (billed).
    await init_db()
    facade = LangGraphRequestFacade(use_real_agents=True)

    request_id = await facade.process_new_request(REQUEST, RESEARCHER)

    async with get_db_session() as session:
        result = await session.execute(
            select(AgentExecution).where(AgentExecution.request_id == request_id)
        )
        executions = result.scalars().all()
    assert executions
    assert {e.agent_id for e in executions} >= {"requirements_agent"}
