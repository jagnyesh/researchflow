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


async def _context() -> dict:
    await init_db()
    request_id = f"REQ-264-{uuid.uuid4().hex[:8].upper()}"
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="Synthetic Researcher",
                researcher_email="r264@example.test",
                initial_request="Adults with type 2 diabetes and their HbA1c",
                current_state="requirements_gathering",
            )
        )
    return {
        "request_id": request_id,
        "initial_request": "Adults with type 2 diabetes and their HbA1c",
        "from_formal_portal": True,
        "researcher_info": {
            "name": "Synthetic Researcher",
            "email": "r264@example.test",
            "structured_requirements": dict(SUBMITTED),
        },
    }


@pytest.mark.asyncio
async def test_without_an_llm_the_request_fails_instead_of_merging_canned_output(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    agent = RequirementsAgent()
    assert agent.llm_client.client is None, "precondition: keyless"

    with pytest.raises(Exception) as excinfo:
        await agent.execute_task("gather_requirements", await _context())

    assert "dummy criterion" not in str(excinfo.value)


def _available_llm(agent, extracted, concepts=None, fail_concepts=False):
    """Stub only the provider-facing calls; the agent's own logic runs for real."""
    agent.llm_client.client = object()  # "initialized"

    async def extract_requirements(**_kwargs):
        return {"extracted_requirements": extracted, "completeness_score": 0.9}

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

    result = await agent.execute_task("gather_requirements", await _context())

    reqs = result["structured_requirements"]
    assert [c["description"] for c in reqs["inclusion_criteria"]] == ["type 2 diabetes"]
    assert reqs["data_elements"] == ["HbA1c"]
    assert reqs["irb_number"] == "IRB-FILLED", "a field the form left blank may be filled"


@pytest.mark.asyncio
async def test_a_criterion_whose_concept_extraction_fails_stops_the_request():
    from app.agents.requirements_agent import CriteriaNotStructuredError

    agent = RequirementsAgent()
    _available_llm(agent, extracted={}, fail_concepts=True)

    with pytest.raises(CriteriaNotStructuredError) as excinfo:
        await agent.execute_task("gather_requirements", await _context())
    assert "diabetes" not in str(excinfo.value), "error text must not echo the criterion"


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
