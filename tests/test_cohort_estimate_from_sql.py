"""#206: the cohort estimate is the approved phenotype SQL's count.

The estimate came from a second implementation (HybridRunner over
patient_simple plus Python filters) that dropped the requirements agent's
`term: "gender"` / `term: "age"` concepts and widened on anything it didn't
parse: 156 estimated vs 13 from the approved SQL. Decided 2026-11-04: one
cohort definition; the estimate counts the phenotype SQL on the batch tables.

Live against HAPI (:5433), read-only: the agent and the oracle only SELECT.
"""

import socket

import pytest

from app.adapters.sql_on_fhir import SQLonFHIRAdapter
from app.agents.phenotype_agent import PhenotypeValidationAgent
from app.utils.sql_generator import SQLGenerator

HAPI = "postgresql://hapi:hapi@localhost:5433/hapi"

# The concept shapes the requirements agent emitted for REQ-20261030-B2B6AD86.
REQUIREMENTS = {
    "inclusion_criteria": [
        {
            "description": "female",
            "concepts": [{"type": "demographic", "term": "gender", "details": "female"}],
        },
        {
            "description": "older than 65",
            "concepts": [{"type": "demographic", "term": "age", "details": "> 65"}],
        },
        {
            "description": "diabetes mellitus",
            "concepts": [{"type": "condition", "term": "diabetes mellitus"}],
        },
    ],
    "exclusion_criteria": [],
    "data_elements": ["demographics"],
    "time_period": {"start": None, "end": None},
}


def _hapi_reachable():
    try:
        with socket.create_connection(("localhost", 5433), timeout=0.5):
            return True
    except OSError:
        return False


async def _sql_count(requirements):
    sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
        requirements, count_only=True
    )
    rows = await SQLonFHIRAdapter(HAPI).execute_sql(sql, params)
    return rows[0]["patient_count"]


def _agent(monkeypatch):
    agent = PhenotypeValidationAgent(database_url=HAPI)

    async def availability(*_a, **_k):
        return {"overall_availability": 0.9, "by_element": {}}

    async def no_save(*_a, **_k):
        return None

    monkeypatch.setattr(agent, "_check_data_availability", availability)
    monkeypatch.setattr(agent, "_save_feasibility_report", no_save)
    return agent


@pytest.mark.asyncio
@pytest.mark.requires_services
@pytest.mark.skipif(not _hapi_reachable(), reason="HAPI Postgres (:5433) not running")
async def test_the_estimate_equals_the_approved_sqls_count(monkeypatch):
    expected = await _sql_count(REQUIREMENTS)

    result = await _agent(monkeypatch).execute_task(
        "validate_feasibility", {"requirements": REQUIREMENTS, "request_id": "REQ-206"}
    )

    assert result["estimated_cohort_size"] == expected
    assert result["additional_context"]["approval_data"]["estimated_cohort"] == expected


@pytest.mark.asyncio
@pytest.mark.requires_services
@pytest.mark.skipif(not _hapi_reachable(), reason="HAPI Postgres (:5433) not running")
async def test_adding_a_criterion_never_widens_the_estimate(monkeypatch):
    agent = _agent(monkeypatch)
    condition_only = dict(REQUIREMENTS, inclusion_criteria=REQUIREMENTS["inclusion_criteria"][2:])

    narrow = await agent.execute_task(
        "validate_feasibility", {"requirements": REQUIREMENTS, "request_id": "REQ-206"}
    )
    broad = await agent.execute_task(
        "validate_feasibility", {"requirements": condition_only, "request_id": "REQ-206"}
    )

    assert narrow["estimated_cohort_size"] <= broad["estimated_cohort_size"]
