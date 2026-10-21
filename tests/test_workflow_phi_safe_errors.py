"""Agent failures in the LangGraph workflow leak no exception text (#181).

Each `_handle_*` node logged `{e}`, wrote `f"... error: {str(e)}"` into
`state["error"]` (persisted to research_requests.error_message) and passed
`str(e)` to `_track_agent_execution_complete` (persisted to
agent_executions.error). Agent exceptions can carry SQL bound params or row
values (#175, ADR 0029). Drives the real node against the real SQLite DB with
one agent double that raises a PHI needle.
"""

import logging
import re
import uuid

import pytest
from sqlalchemy import select

PHI_NEEDLE = "patient WW-2201 dob 1961-04-09 HbA1c 8.8"


class RaisingAgent:
    async def execute_task(self, task, context):
        raise RuntimeError(PHI_NEEDLE)


@pytest.fixture
async def workflow():
    from app.database import init_db
    from app.langchain_orchestrator.langgraph_workflow import FullWorkflow

    await init_db()
    wf = FullWorkflow(use_real_agents=False)
    wf.use_real_agents = True  # route nodes to the (double) agents, not stubs
    return wf


async def _persisted_errors(request_id):
    from app.database import get_db_session
    from app.database.models import AgentExecution

    async with get_db_session() as session:
        rows = await session.execute(
            select(AgentExecution.error).where(AgentExecution.request_id == request_id)
        )
        return [e for (e,) in rows.all()]


@pytest.mark.asyncio
async def test_phenotype_failure_keeps_phi_out_of_state_logs_and_db(workflow, caplog):
    workflow.phenotype_agent = RaisingAgent()
    request_id = f"REQ-181-{uuid.uuid4().hex[:8]}"
    state = {
        "request_id": request_id,
        "requirements": {},
        "researcher_info": {},
    }

    with caplog.at_level(logging.DEBUG):
        state = await workflow._handle_feasibility_validation(state)

    assert state["error"], "the node must still flag the failure"
    assert PHI_NEEDLE not in state["error"]
    assert PHI_NEEDLE not in caplog.text
    ref = re.search(r"ref: ([0-9a-f]{12})", state["error"]).group(1)
    assert ref in caplog.text
    persisted = await _persisted_errors(request_id)
    assert persisted and all(PHI_NEEDLE not in (e or "") for e in persisted)


NODES = [
    ("_handle_requirements_gathering", "requirements_agent"),
    ("_handle_feasibility_validation", "phenotype_agent"),
    ("_handle_preview_extraction", "extraction_agent"),
    ("_handle_preview_qa", "qa_agent"),
    ("_handle_schedule_kickoff", "calendar_agent"),
    ("_handle_data_extraction", "extraction_agent"),
    ("_handle_qa_validation", "qa_agent"),
    ("_handle_data_delivery", "delivery_agent"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("node, agent_attr", NODES)
async def test_every_agent_node_keeps_phi_out(workflow, caplog, node, agent_attr):
    setattr(workflow, agent_attr, RaisingAgent())
    request_id = f"REQ-181-{uuid.uuid4().hex[:8]}"
    state = {
        "request_id": request_id,
        "requirements": {},
        "researcher_info": {},
        "researcher_request": "",
        "phenotype_sql": "SELECT 1",
        "sql_parameters": {},
        "preview_package": {},
        "extracted_data": {},
        "qa_report": {},
    }

    with caplog.at_level(logging.DEBUG):
        state = await getattr(workflow, node)(state)

    assert state.get("error"), f"{node} must still flag the failure"
    assert PHI_NEEDLE not in repr(dict(state))
    assert PHI_NEEDLE not in caplog.text
    assert all(PHI_NEEDLE not in (e or "") for e in await _persisted_errors(request_id))


GUARDED_DIRS = ["app/langchain_orchestrator", "app/agents"]


@pytest.mark.parametrize("rel", GUARDED_DIRS)
def test_no_exception_text_escapes_in_workflow_code(rel):
    """The #175 AST guard, extended to the workflow path (#181)."""
    import ast
    from pathlib import Path

    from tests.test_api_error_leak import _banned_calls, _handler_leaks

    root = Path(__file__).resolve().parents[1] / rel
    violations = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        violations += [f"{path.name}:{n}" for n in _handler_leaks(tree)]
        violations += [f"{path.name}:{n} (banned call)" for n in _banned_calls(tree)]
    assert not violations, f"{rel}: " + ", ".join(violations)
