"""#264: a missing or failing requirements LLM never changes or drops a formal
request's submitted criteria. The request keeps the form, or fails visibly.

Real RequirementsAgent and SQLGenerator; only the LLM client's provider-facing
methods are stubbed. Run keyless (ANTHROPIC_API_KEY empty) like CI.
"""

import uuid

import pytest

from app.agents.requirements_agent import RequirementsAgent
from app.database import ResearchRequest, get_db_session, init_db
from app.utils.sql_generator import SQLGenerator

SUBMITTED = {
    "inclusion_criteria": ["type 2 diabetes"],
    "exclusion_criteria": [],
    "data_elements": ["HbA1c"],
}


async def _context(
    structured=None, initial_request="Adults with type 2 diabetes and their HbA1c"
) -> dict:
    await init_db()
    request_id = f"REQ-264-{uuid.uuid4().hex[:8].upper()}"
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="Synthetic Researcher",
                researcher_email="r264@example.test",
                initial_request=initial_request or "(blank)",
                current_state="requirements_gathering",
            )
        )
    return {
        "request_id": request_id,
        "initial_request": initial_request,
        "from_formal_portal": True,
        "researcher_info": {
            "name": "Synthetic Researcher",
            "email": "r264@example.test",
            "irb_number": "IRB-REAL",
            "structured_requirements": dict(SUBMITTED if structured is None else structured),
        },
    }


@pytest.mark.asyncio
async def test_without_an_llm_the_request_fails_instead_of_merging_canned_output(monkeypatch):
    from app.agents.requirements_agent import CriteriaNotStructuredError

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    agent = RequirementsAgent()
    assert agent.llm_client.client is None, "precondition: keyless"
    merged = []
    real_extract = agent.llm_client.extract_requirements

    async def spy(**kwargs):
        merged.append(kwargs)
        return await real_extract(**kwargs)

    agent.llm_client.extract_requirements = spy

    with pytest.raises(CriteriaNotStructuredError):
        await agent.execute_task("gather_requirements", await _context())
    assert merged == [], "no canned LLM output may be merged without a client"


def _available_llm(agent, extracted, concepts=None, fail_concepts=False):
    """Stub only the provider-facing calls; the agent's own logic runs for real."""
    agent.llm_client.client = object()  # "initialized"

    _available_llm.extracted = extracted

    async def extract_requirements(**_kwargs):
        return {"extracted_requirements": _available_llm.extracted, "completeness_score": 0.9}

    async def batch(criteria):
        if fail_concepts:
            raise ConnectionError("provider down")
        return [{"concepts": concepts or []} for _ in criteria]

    async def single(_criterion):
        if fail_concepts:
            raise ConnectionError("provider down")
        return {"concepts": concepts or []}

    agent.llm_client.extract_requirements = extract_requirements
    agent.llm_client.extract_medical_concepts_batch = batch
    agent.llm_client.extract_medical_concepts = single


@pytest.mark.asyncio
async def test_the_llm_fills_gaps_but_never_overwrites_submitted_fields():
    agent = RequirementsAgent()
    _available_llm(
        agent,
        extracted={
            "inclusion_criteria": ["something else"],
            "data_elements": ["clinical_notes"],
            "irb_number": "IRB-FILLED",
        },
        concepts=[{"type": "condition", "term": "type 2 diabetes"}],
    )

    _available_llm.extracted["principal_investigator"] = "Someone Else"
    _available_llm.extracted["study_title"] = "LLM-written title"
    context = await _context()

    result = await agent.execute_task("gather_requirements", context)

    reqs = result["structured_requirements"]
    assert [c["description"] for c in reqs["inclusion_criteria"]] == ["type 2 diabetes"]
    assert reqs["data_elements"] == ["HbA1c"]
    assert reqs["irb_number"] == "IRB-REAL", "the submitted IRB number is the researcher's"
    assert reqs["principal_investigator"] == "Synthetic Researcher"
    assert reqs["study_title"] == "LLM-written title", "a field the form doesn't send may be filled"


@pytest.mark.asyncio
async def test_blank_dates_mean_no_time_filter():
    # The portal's date pickers default to blank: {"start": None, "end": None}.
    agent = RequirementsAgent()
    _available_llm(
        agent,
        extracted={"time_period": {"start": "2022-01-01", "end": "2024-12-31"}},
        concepts=[{"type": "condition", "term": "type 2 diabetes"}],
    )

    result = await agent.execute_task(
        "gather_requirements",
        await _context(structured={**SUBMITTED, "time_period": {"start": None, "end": None}}),
    )

    reqs = result["structured_requirements"]
    assert reqs["time_period"] == {"start": None, "end": None}
    sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        reqs, count_only=True
    )
    assert not any(k.startswith(("start_date", "end_date")) for k in params), params


@pytest.mark.asyncio
async def test_an_empty_batch_entry_is_retried_per_criterion():
    agent = RequirementsAgent()
    _available_llm(agent, extracted={})
    single_calls = []

    async def batch(criteria):
        return [{"concepts": []} for _ in criteria]  # numbering-mismatch placeholder

    async def single(criterion):
        single_calls.append(criterion)
        return {"concepts": [{"type": "condition", "term": "type 2 diabetes"}]}

    agent.llm_client.extract_medical_concepts_batch = batch
    agent.llm_client.extract_medical_concepts = single

    result = await agent.execute_task("gather_requirements", await _context())

    assert single_calls == ["type 2 diabetes"]
    assert result["structured_requirements"]["inclusion_criteria"][0]["concepts"]


@pytest.mark.asyncio
async def test_a_criterion_whose_concept_extraction_fails_stops_the_request():
    from app.agents.requirements_agent import CriteriaNotStructuredError

    agent = RequirementsAgent()
    _available_llm(agent, extracted={}, fail_concepts=True)

    with pytest.raises(CriteriaNotStructuredError) as excinfo:
        await agent.execute_task("gather_requirements", await _context())
    assert "diabetes" not in str(excinfo.value), "error text must not echo the criterion"


@pytest.mark.asyncio
async def test_a_blank_inclusion_box_falls_back_to_the_request_text():
    # The portal sends [] for the optional inclusion box; [] must not be "submitted"
    # (that left the criteria empty and built an all-patient COUNT).
    agent = RequirementsAgent()
    _available_llm(agent, extracted={}, concepts=[{"type": "condition", "term": "type 2 diabetes"}])

    result = await agent.execute_task(
        "gather_requirements", await _context(structured={**SUBMITTED, "inclusion_criteria": []})
    )

    inclusion = result["structured_requirements"]["inclusion_criteria"]
    assert [c["description"] for c in inclusion] == ["Adults with type 2 diabetes and their HbA1c"]
    sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        result["structured_requirements"], count_only=True
    )
    assert params, "the cohort must be filtered"


@pytest.mark.asyncio
async def test_a_request_with_no_criteria_at_all_is_refused():
    from app.agents.requirements_agent import CriteriaNotStructuredError

    agent = RequirementsAgent()
    _available_llm(agent, extracted={}, concepts=[{"type": "condition", "term": "x"}])

    with pytest.raises(CriteriaNotStructuredError):
        await agent.execute_task(
            "gather_requirements",
            await _context(structured={**SUBMITTED, "inclusion_criteria": []}, initial_request=""),
        )


def test_sql_generator_refuses_criteria_that_build_no_conditions():
    requirements = {
        "inclusion_criteria": [{"description": "type 2 diabetes", "concepts": [], "codes": []}],
        "exclusion_criteria": [],
        "data_elements": ["demographics"],
    }

    with pytest.raises(ValueError, match="0 WHERE conditions"):
        SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
            requirements, count_only=True
        )


def test_sql_generator_still_builds_sql_for_a_structured_criterion():
    requirements = {
        "inclusion_criteria": [
            {
                "description": "type 2 diabetes",
                "concepts": [{"type": "condition", "term": "type 2 diabetes"}],
                "codes": [],
            }
        ],
        "exclusion_criteria": [],
        "data_elements": ["demographics"],
    }

    sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        requirements, count_only=True
    )
    assert params, "the condition should be a bound parameter"


@pytest.mark.asyncio
async def test_a_failed_formal_request_shows_as_an_error_not_in_progress(tmp_path, monkeypatch):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy import select

    from app.database.models import Approval
    from app.langchain_orchestrator.langgraph_workflow import FullWorkflow
    from app.langchain_orchestrator.request_facade import LangGraphRequestFacade

    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.delenv("AUTO_APPROVE_FOR_DEV", raising=False)
    original_init = FullWorkflow.__init__

    def init_with_keyless_requirements_agent(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Only the requirements node runs a real agent; the rest stay on stubs.
        self.use_real_agents = True
        self.requirements_agent = RequirementsAgent()

    monkeypatch.setattr(FullWorkflow, "__init__", init_with_keyless_requirements_agent)
    await init_db()
    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)
    await facade._ensure_initialized()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.db")) as saver:

        async def checkpointer():
            return saver

        facade.checkpointer_factory = checkpointer
        context = await _context()
        request_id = await facade.process_new_request(
            context["initial_request"], context["researcher_info"], from_formal_portal=True
        )

    async with get_db_session() as session:
        row = await session.get(ResearchRequest, request_id)
        approvals = (
            (await session.execute(select(Approval).where(Approval.request_id == request_id)))
            .scalars()
            .all()
        )
    assert row.current_state == "error"
    assert "CriteriaNotStructuredError" in (row.error_message or "")
    assert "diabetes" not in row.error_message
    assert [a.approval_type for a in approvals] == [], "must stop before any review gate"
