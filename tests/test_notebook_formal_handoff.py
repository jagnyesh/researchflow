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


async def _notebook_gather(agent, query):
    from app.web_ui.research_notebook import formal_structured_requirements

    return await agent.execute_task(
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


async def _outage(*_a, **_k):
    raise ConnectionError("provider down")


@pytest.mark.asyncio
async def test_criteria_survive_a_failed_validation_call(monkeypatch):
    from app.agents.requirements_agent import RequirementsAgent

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    agent = RequirementsAgent()
    # A stand-in client, so the validation call is made and fails, not skipped.
    monkeypatch.setattr(agent.llm_client, "client", object())
    monkeypatch.setattr(agent.llm_client, "extract_requirements", _outage)

    async def concepts(criteria):
        return [{"concepts": [{"term": "type 2 diabetes", "type": "condition"}]} for _ in criteria]

    monkeypatch.setattr(agent.llm_client, "extract_medical_concepts_batch", concepts)

    query = "How many patients with type 2 diabetes?"
    result = await _notebook_gather(agent, query)

    inclusion = result["structured_requirements"]["inclusion_criteria"]
    assert query in str(inclusion), inclusion


@pytest.mark.asyncio
async def test_a_concept_extraction_outage_fails_visibly(monkeypatch):
    # Unstructured criteria build no SQL condition, so the cohort would silently
    # ignore them (#264); the hand-off must fail instead.
    from app.agents.requirements_agent import CriteriaNotStructuredError, RequirementsAgent

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    agent = RequirementsAgent()
    for name in (
        "extract_requirements",
        "extract_medical_concepts_batch",
        "extract_medical_concepts",
    ):
        monkeypatch.setattr(agent.llm_client, name, _outage)

    with pytest.raises(CriteriaNotStructuredError):
        await _notebook_gather(agent, "How many patients with type 2 diabetes?")


# --- #364: typing "proceed" reaches the hand-off, with the researcher's query ---

QUERY = "How many women with hypertension are under 65?"
RESULT = {
    "status": "ok",
    "estimated_cohort": 1284,
    "generated_sql": "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p",
    "time_period": {},
}


def _proceed_app(submitted: list, fail: bool = False):
    """The notebook page, driven by AppTest. Stubbed: intent detection and the
    feasibility check (LLM), and the facade's process_new_request (database +
    workflow), which records what the page sends it."""
    from pathlib import Path
    from unittest.mock import patch

    from streamlit.testing.v1 import AppTest

    from app.services.conversation_manager import ConversationManager, UserIntent
    from app.services.feasibility_service import FeasibilityService

    notebook = str(Path(__file__).resolve().parents[1] / "app" / "web_ui" / "research_notebook.py")
    at = AppTest.from_file(notebook, default_timeout=60).run()

    async def intent(self, text):
        return UserIntent.CONFIRMATION if text == "proceed" else UserIntent.QUERY

    async def confirmed(self, text):
        return True

    async def check(self, query_intent, natural_language_query=None):
        return dict(RESULT)

    async def close(self):
        return None

    async def process(self, researcher_request, researcher_info, from_formal_portal=False):
        if fail:
            raise RuntimeError("workflow down")
        submitted.append(researcher_request)
        return "REQ-364"

    patches = (
        patch.object(ConversationManager, "detect_intent", intent),
        patch.object(ConversationManager, "is_confirmation", confirmed),
        patch.object(FeasibilityService, "execute_feasibility_check", check),
        patch.object(FeasibilityService, "close", close),
        patch.object(LangGraphRequestFacade, "process_new_request", process),
    )
    for p in patches:
        p.start()
    return at, patches


def _stop(patches):
    for p in patches:
        p.stop()


def test_proceed_submits_the_researchers_query_not_the_assistants_reply():
    submitted: list = []
    at, patches = _proceed_app(submitted)
    try:
        at.chat_input[0].set_value(QUERY).run()
        at.chat_input[0].set_value("proceed").run()
    finally:
        _stop(patches)

    assert not at.exception
    assert submitted == [QUERY]
    assert at.session_state["pending_request_id"] == "REQ-364"
    assert "REQ-364" in at.session_state["messages"][-1]["content"]


def test_a_second_proceed_does_not_submit_a_duplicate_request():
    submitted: list = []
    at, patches = _proceed_app(submitted)
    try:
        at.chat_input[0].set_value(QUERY).run()
        at.chat_input[0].set_value("proceed").run()
        at.chat_input[0].set_value("proceed").run()
    finally:
        _stop(patches)

    assert submitted == [QUERY]


def test_a_failed_submit_says_so_and_keeps_the_count_confirmable():
    submitted: list = []
    at, patches = _proceed_app(submitted, fail=True)
    try:
        at.chat_input[0].set_value(QUERY).run()
        at.chat_input[0].set_value("proceed").run()
    finally:
        _stop(patches)

    assert submitted == []
    assert at.session_state["pending_request_id"] is None
    reply = at.session_state["messages"][-1]["content"]
    assert "Could not submit" in reply
    assert "workflow down" not in reply  # ADR 0029: a ref, never the exception text
    assert at.session_state["conversation_state"].name == "AWAITING_CONFIRMATION"


def test_proceed_after_a_refined_question_submits_the_latest_query():
    submitted: list = []
    at, patches = _proceed_app(submitted)
    refined = "How many women with hypertension are under 50?"
    try:
        at.chat_input[0].set_value(QUERY).run()
        at.chat_input[0].set_value(refined).run()
        at.chat_input[0].set_value("proceed").run()
    finally:
        _stop(patches)

    assert submitted == [refined]
