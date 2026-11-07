"""#343: POST /approvals/scope-change opens a scope_change approval.

It always returned 500 "Coordinator agent not available": the route looked up
an agent that was never registered. Real facade (stub agents, no LLM),
real test database, the router mounted alone.
"""

import httpx
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select

from app.api import approvals as approvals_api
from app.database import get_db_session, init_db
from app.database.models import Approval
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade
from app.services.scope_change import analyze_scope_change_impact

RESEARCHER = {"name": "Dr. Synthetic", "email": "synthetic@example.org"}


@pytest.fixture
async def facade(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DELIVERY_PATH", str(tmp_path))
    monkeypatch.delenv("AUTO_APPROVE_FOR_DEV", raising=False)
    await init_db()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        f = LangGraphRequestFacade(use_real_agents=False)
        await f._ensure_initialized()

        async def checkpointer():
            return saver

        f.checkpointer_factory = checkpointer
        yield f
        await f.close()


async def _post(facade, monkeypatch, body):
    api = FastAPI()
    api.include_router(approvals_api.router)
    monkeypatch.setattr(approvals_api, "orchestrator", facade)
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/approvals/scope-change", json=body)


@pytest.mark.asyncio
async def test_a_scope_change_opens_an_approval_carrying_its_impact(facade, monkeypatch):
    request_id = await facade.process_new_request("female patients with diabetes", RESEARCHER)

    response = await _post(
        facade,
        monkeypatch,
        {
            "request_id": request_id,
            "requested_by": "synthetic@example.org",
            "requested_changes": {"data_elements": ["medications"]},
            "reason": "need medications too",
        },
    )

    assert response.status_code == 200, response.text
    async with get_db_session() as session:
        approval = (
            await session.execute(
                select(Approval).where(Approval.id == response.json()["approval_id"])
            )
        ).scalar_one()
    assert approval.approval_type == "scope_change"
    assert approval.request_id == request_id
    assert (
        approval.approval_data["impact_analysis"]["restart_from_state"] == "feasibility_validation"
    )


def test_criteria_changes_restart_from_requirements():
    impact = analyze_scope_change_impact({"inclusion_criteria": ["hypertension"]})

    assert impact["severity"] == "high"
    assert impact["restart_from_state"] == "requirements_gathering"
    assert impact["affected_components"] == ["phenotype", "extraction", "qa"]


def test_an_unrecognized_change_still_reports_an_impact():
    impact = analyze_scope_change_impact({"delivery_format": "parquet"})

    assert impact == {
        "severity": "medium",
        "requires_rework": False,
        "restart_from_state": None,
        "estimated_delay_hours": 0,
        "affected_components": [],
    }
