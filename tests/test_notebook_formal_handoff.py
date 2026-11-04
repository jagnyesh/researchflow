"""#273: the Research Notebook's formal hand-off starts the workflow.

It posted to /research/submit (whose workflow start was only a comment) and
/research/process (route_task, a no-op under LangGraph), so the researcher
saw success and nothing ran. It now starts the request through
LangGraphRequestFacade in-process, as the formal portal does. Real facade
with stub agents, real SQLite checkpointer and DB.
"""

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select

from app.database import ResearchRequest, get_db_session, init_db
from app.database.models import Approval
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade

STRUCTURED = {
    "study_title": "Research Notebook Query",
    "principal_investigator": "Research Notebook User",
    "inclusion_criteria": ["type 2 diabetes"],
    "exclusion_criteria": [],
    "data_elements": ["demographics"],
    "time_period": {"start": None, "end": None},
    "delivery_format": "CSV",
    "phi_level": "de-identified",
}


@pytest.mark.asyncio
async def test_the_handoff_runs_the_workflow_to_its_first_review_gate(tmp_path, monkeypatch):
    from app.web_ui.research_notebook import start_formal_request

    monkeypatch.delenv("AUTO_APPROVE_FOR_DEV", raising=False)
    await init_db()
    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)
    await facade._ensure_initialized()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.db")) as saver:

        async def checkpointer():
            return saver

        facade.checkpointer_factory = checkpointer
        request_id = await start_formal_request(
            facade, "How many patients with type 2 diabetes?", STRUCTURED
        )

    async with get_db_session() as session:
        request = await session.get(ResearchRequest, request_id)
        gates = (
            (await session.execute(select(Approval).where(Approval.request_id == request_id)))
            .scalars()
            .all()
        )
    assert request.current_state not in ("new_request", "requirements_gathering")
    assert [(g.approval_type, g.status) for g in gates] == [("phenotype_sql", "pending")]


def test_the_dead_end_routes_are_gone():
    from app.api import research

    paths = {route.path for route in research.router.routes}
    assert "/research/submit" not in paths
    assert "/research/process/{request_id}" not in paths
