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


def test_the_notebook_payload_sends_only_what_it_knows():
    from app.web_ui.research_notebook import formal_structured_requirements

    payload = formal_structured_requirements({"estimated_cohort": 42})

    # The exploratory path has no parsed criteria (QueryIntent was retired in
    # #100); sending empty lists overrode the requirements agent's fallback to
    # the query text. Blank dates mean no time filter.
    for key in ("inclusion_criteria", "exclusion_criteria", "data_elements"):
        assert key not in payload
    assert payload["time_period"] == {"start": None, "end": None}


@pytest.mark.asyncio
async def test_criteria_survive_a_failed_llm_call(monkeypatch):
    from app.agents.requirements_agent import RequirementsAgent
    from app.web_ui.research_notebook import formal_structured_requirements

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    agent = RequirementsAgent()

    async def outage(*_a, **_k):
        raise ConnectionError("provider down")

    monkeypatch.setattr(agent.llm_client, "extract_requirements", outage)
    monkeypatch.setattr(agent.llm_client, "extract_medical_concepts_batch", outage)
    monkeypatch.setattr(agent.llm_client, "extract_medical_concepts", outage)

    query = "How many patients with type 2 diabetes?"
    result = await agent.execute_task(
        "gather_requirements",
        {
            "request_id": "REQ-273-PAYLOAD",
            "initial_request": query,
            "from_formal_portal": True,
            "researcher_info": {
                "name": "Research Notebook User",
                "email": "researcher@hospital.org",
                "irb_number": "IRB-NOTEBOOK-001",
                "structured_requirements": formal_structured_requirements({"estimated_cohort": 42}),
            },
        },
    )

    inclusion = result["structured_requirements"]["inclusion_criteria"]
    assert query in str(inclusion), inclusion
