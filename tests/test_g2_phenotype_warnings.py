"""#265: G2 reviewers see the phenotype agent's warnings and recommendations.

LangGraph drops state keys missing from FullWorkflowState between nodes, so
the G2 payload read keys nothing could carry. Drives the real facade ->
FullWorkflow -> phenotype node -> G2 approval row; the phenotype agent is the
only double, returning the real agent's result shape.
"""

import ast
import inspect
import textwrap

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select

from app.database import get_db_session, init_db
from app.database.models import Approval
from app.langchain_orchestrator.approval_bridge import ApprovalBridge
from app.langchain_orchestrator.langgraph_workflow import FullWorkflow, FullWorkflowState
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade

WARNING = {
    "type": "small_cohort",
    "message": "Estimated cohort (12) smaller than requested minimum (50)",
}
RECOMMENDATION = {"suggestion": "Broaden the age range"}


def _state_keys_read(func) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    keys = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "state"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            keys.add(node.args[0].value)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "state"
            and isinstance(node.slice, ast.Constant)
        ):
            keys.add(node.slice.value)
    return keys


def test_every_key_the_approval_payload_reads_is_declared_state():
    read = _state_keys_read(ApprovalBridge._extract_approval_data)
    assert read, "parsed no state reads; the guard would pass vacuously"

    assert read - set(FullWorkflowState.__annotations__) == set()


class _FakePhenotypeAgent:
    """Returns the shape PhenotypeValidationAgent._validate_feasibility returns."""

    async def execute_task(self, task, context):
        report = {
            "feasible": True,
            "data_availability": {"overall_availability": 0.8},
            "estimated_extraction_time_hours": 2.5,
            "warnings": [WARNING],
            "recommendations": [RECOMMENDATION],
        }
        return {
            "feasible": True,
            "estimated_cohort_size": 12,
            "phenotype_sql": "SELECT COUNT(*) FROM sqlonfhir.patient_simple WHERE gender = :g",
            "feasibility_score": 0.4,
            "feasibility_report": report,
            "additional_context": {
                "feasibility_report": report,
                "approval_data": {
                    "parameters": {"g": "female"},
                    "data_availability": report["data_availability"],
                    "warnings": report["warnings"],
                    "recommendations": report["recommendations"],
                    "auto_feasibility_assessment": "feasible",
                },
            },
        }


@pytest.fixture
async def saver(tmp_path):
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as s:
        yield s


@pytest.fixture
async def facade(saver, monkeypatch):
    monkeypatch.delenv("AUTO_APPROVE_FOR_DEV", raising=False)
    original_init = FullWorkflow.__init__

    def init_with_fake_phenotype_agent(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Only the phenotype node takes its real-agent branch; every other
        # node needs its own agent instance, which stays None (stub path).
        self.use_real_agents = True
        self.phenotype_agent = _FakePhenotypeAgent()

    monkeypatch.setattr(FullWorkflow, "__init__", init_with_fake_phenotype_agent)
    await init_db()
    f = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)
    await f._ensure_initialized()

    async def checkpointer():
        return saver

    f.checkpointer_factory = checkpointer
    return f


@pytest.mark.asyncio
async def test_g2_approval_carries_the_phenotype_agents_warnings(facade):
    request_id = await facade.process_new_request(
        "Synthetic test request",
        {"name": "Test Researcher", "email": "researcher@example.test"},
        from_formal_portal=True,
    )

    async with get_db_session() as session:
        approval = (
            await session.execute(
                select(Approval).where(
                    Approval.request_id == request_id, Approval.approval_type == "phenotype_sql"
                )
            )
        ).scalar_one()

    data = approval.approval_data
    assert data["warnings"] == [WARNING]
    assert data["recommendations"] == [RECOMMENDATION]
    assert data["data_availability"] == {"overall_availability": 0.8}
    assert data["auto_feasibility_assessment"] == "feasible"
    assert data["estimated_extraction_time_hours"] == 2.5
