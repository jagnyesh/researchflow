"""#245: a cohort-estimation error never reaches G2 as a number.

Real PhenotypeValidationAgent; only the database read (the SQL adapter;
#206 retired the HybridRunner path) raises, plus the data-availability lookup and report save are
stubbed. Run keyless.
"""

import pytest

from app.agents.phenotype_agent import PhenotypeValidationAgent

REQUIREMENTS = {
    "inclusion_criteria": [
        {
            "description": "diabetes mellitus",
            "concepts": [{"type": "condition", "term": "diabetes mellitus"}],
        },
        {
            "description": "female over 65",
            "concepts": [{"type": "demographic", "term": "female", "details": "age > 65"}],
        },
    ],
    "exclusion_criteria": [],
    "data_elements": ["demographics"],
    "time_period": {"start": None, "end": None},
}


def _agent(monkeypatch, *, sql_fails=False):
    agent = PhenotypeValidationAgent()
    if sql_fails:

        async def execute_sql(*_a, **_k):
            raise ConnectionError("database unreachable")

        monkeypatch.setattr(agent.sql_adapter, "execute_sql", execute_sql)

    async def availability(*_a, **_k):
        return {"overall_availability": 0.9, "by_element": {}}

    async def no_save(*_a, **_k):
        return None

    suggested = []

    async def suggest(*_a, **_k):
        suggested.append(True)
        return [{"suggestion": "Consider broadening inclusion criteria"}]

    monkeypatch.setattr(agent, "_check_data_availability", availability)
    monkeypatch.setattr(agent, "_save_feasibility_report", no_save)
    monkeypatch.setattr(agent, "_suggest_alternative_criteria", suggest)
    return agent, suggested


def _assert_unavailable(result, suggested):
    approval = result["additional_context"]["approval_data"]
    report = result["feasibility_report"]
    for value in (
        result["estimated_cohort"],
        result["estimated_cohort_size"],
        result["feasibility_score"],
        report["estimated_cohort_size"],
        report["feasibility_score"],
        approval["estimated_cohort"],
        approval["feasibility_score"],
    ):
        assert value is None
    assert report["cohort_estimate"]["status"] == "unavailable"
    ref = report["cohort_estimate"]["error_ref"]
    assert ref and len(ref) == 12
    assert approval["auto_feasibility_assessment"] == "unavailable"
    types = [w["type"] for w in report["warnings"]]
    assert "small_cohort" not in types
    [unavailable] = [w for w in report["warnings"] if w["type"] == "cohort_estimate_unavailable"]
    assert ref in unavailable["message"]
    assert approval["warnings"] == report["warnings"]
    assert report["recommendations"] == [] and suggested == []
    # The SQL still goes to review.
    assert result["phenotype_sql"] and result["requires_approval"] is True


@pytest.mark.asyncio
async def test_a_count_query_error_is_an_unavailable_estimate(monkeypatch):
    agent, suggested = _agent(monkeypatch, sql_fails=True)

    result = await agent.execute_task(
        "validate_feasibility", {"requirements": REQUIREMENTS, "request_id": "REQ-245"}
    )

    _assert_unavailable(result, suggested)


@pytest.mark.asyncio
async def test_an_unavailable_estimate_is_saved_without_a_cohort_count(monkeypatch):
    import uuid

    from sqlalchemy import select

    from app.database import FeasibilityReport, ResearchRequest, get_db_session, init_db

    await init_db()
    request_id = f"REQ-245-{uuid.uuid4().hex[:8].upper()}"
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="Synthetic Researcher",
                researcher_email="r245@example.test",
                initial_request="synthetic",
                current_state="feasibility_validation",
            )
        )
    agent, _ = _agent(monkeypatch, sql_fails=True)
    monkeypatch.undo()  # the real report save

    async def execute_sql(*_a, **_k):
        raise ConnectionError("database unreachable")

    monkeypatch.setattr(agent.sql_adapter, "execute_sql", execute_sql)

    async def availability(*_a, **_k):
        return {"overall_availability": 0.9, "by_element": {}}

    monkeypatch.setattr(agent, "_check_data_availability", availability)

    await agent.execute_task(
        "validate_feasibility", {"requirements": REQUIREMENTS, "request_id": request_id}
    )

    async with get_db_session() as session:
        row = (
            await session.execute(
                select(FeasibilityReport).where(FeasibilityReport.request_id == request_id)
            )
        ).scalar_one()
    assert row.estimated_cohort_size is None
    assert row.confidence_interval_low is None and row.confidence_interval_high is None
    assert row.is_feasible is False
    assert [w["type"] for w in row.warnings] == ["cohort_estimate_unavailable"]


# ---- Workflow: the G2 payload never shows a failed estimate as a number ----


class _RaisingPhenotypeAgent:
    async def execute_task(self, task, context):
        raise ConnectionError("database unreachable")


class _UnavailablePhenotypeAgent:
    """The real agent's shape when its estimate failed (see the tests above)."""

    async def execute_task(self, task, context):
        warning = {
            "type": "cohort_estimate_unavailable",
            "message": "Cohort estimate unavailable: the count query failed (ref: abcdef123456)",
        }
        report = {
            "feasible": False,
            "feasibility_score": None,
            "estimated_cohort_size": None,
            "cohort_estimate": {"status": "unavailable", "error_ref": "abcdef123456"},
            "data_availability": {"overall_availability": 0.9},
            "estimated_extraction_time_hours": None,
            "warnings": [warning],
            "recommendations": [],
        }
        return {
            "feasible": False,
            "estimated_cohort": None,
            "estimated_cohort_size": None,
            "feasibility_score": None,
            "phenotype_sql": "SELECT COUNT(*) FROM sqlonfhir.patient_simple WHERE gender = :g",
            "feasibility_report": report,
            "additional_context": {
                "feasibility_report": report,
                "approval_data": {
                    "parameters": {"g": "female"},
                    "estimated_cohort": None,
                    "feasibility_score": None,
                    "data_availability": report["data_availability"],
                    "warnings": report["warnings"],
                    "recommendations": [],
                    "auto_feasibility_assessment": "unavailable",
                },
            },
        }


async def _g2_payload(agent, tmp_path, monkeypatch):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy import select

    from app.database import get_db_session, init_db
    from app.database.models import Approval
    from app.langchain_orchestrator.langgraph_workflow import FullWorkflow
    from app.langchain_orchestrator.request_facade import LangGraphRequestFacade

    monkeypatch.delenv("AUTO_APPROVE_FOR_DEV", raising=False)
    original_init = FullWorkflow.__init__

    def init_with_phenotype_agent(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.use_real_agents = True  # only the phenotype node has an agent
        self.phenotype_agent = agent

    monkeypatch.setattr(FullWorkflow, "__init__", init_with_phenotype_agent)
    await init_db()
    facade = LangGraphRequestFacade(use_real_agents=False, use_persistence=True)
    await facade._ensure_initialized()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.db")) as saver:

        async def checkpointer():
            return saver

        facade.checkpointer_factory = checkpointer
        request_id = await facade.process_new_request(
            "Synthetic test request",
            {"name": "Test Researcher", "email": "researcher@example.test"},
            from_formal_portal=True,
        )

    async with get_db_session() as session:
        [approval] = (
            (
                await session.execute(
                    select(Approval).where(
                        Approval.request_id == request_id,
                        Approval.approval_type == "phenotype_sql",
                    )
                )
            )
            .scalars()
            .all()
        )
    return approval.approval_data


@pytest.mark.asyncio
async def test_a_phenotype_agent_failure_reaches_g2_without_a_cohort(tmp_path, monkeypatch):
    data = await _g2_payload(_RaisingPhenotypeAgent(), tmp_path, monkeypatch)

    assert data["estimated_cohort_size"] is None
    assert data["feasibility_score"] is None
    estimate = data["cohort_estimate"]
    assert estimate["status"] == "unavailable"
    assert estimate["error_ref"] and len(estimate["error_ref"]) == 12


@pytest.mark.asyncio
async def test_an_unavailable_estimate_reaches_g2_as_unavailable(tmp_path, monkeypatch):
    data = await _g2_payload(_UnavailablePhenotypeAgent(), tmp_path, monkeypatch)

    assert data["estimated_cohort_size"] is None
    assert data["feasibility_score"] is None
    assert data["cohort_estimate"] == {"status": "unavailable", "error_ref": "abcdef123456"}
    assert data["auto_feasibility_assessment"] == "unavailable"
    assert [w["type"] for w in data["warnings"]] == ["cohort_estimate_unavailable"]


def test_a_preview_qa_gate_without_an_estimate_shows_no_expected_count():
    from app.langchain_orchestrator.approval_bridge import ApprovalBridge

    state = {"estimated_cohort_size": None, "preview_package": {"cohort": []}}

    data = ApprovalBridge._extract_approval_data(None, "preview_qa", state)

    details = data["cohort_check"]["details"]
    assert details["estimated_cohort_size"] is None
    assert "unavailable" in data["message"]
    assert "expected: None" not in data["message"]


# ---- Downstream consumers of an unavailable estimate (review pass 1) ----

UNAVAILABLE_REPORT = {
    "estimated_cohort_size": None,
    "feasibility_score": None,
    "cohort_estimate": {"status": "unavailable", "error_ref": "abcdef123456"},
    "warnings": [],
}


def test_the_preview_spinner_message_handles_a_missing_time():
    from app.web_ui.admin_dashboard import preview_time_message

    assert preview_time_message(None) == "Extraction in progress..."
    assert preview_time_message(0) == "Extraction in progress..."
    assert preview_time_message(0.5) == "Estimated time: ~30 minutes"
    assert preview_time_message(2.5) == "Estimated time: ~2.5 hours"


@pytest.mark.asyncio
async def test_an_empty_count_result_is_an_unavailable_estimate(monkeypatch):
    agent, suggested = _agent(monkeypatch)

    async def no_rows(*_a, **_k):
        return []

    monkeypatch.setattr(agent.sql_adapter, "execute_sql", no_rows)

    result = await agent.execute_task(
        "validate_feasibility", {"requirements": REQUIREMENTS, "request_id": "REQ-245"}
    )

    _assert_unavailable(result, suggested)


async def _seed_request(request_id):
    from app.database import ResearchRequest, get_db_session, init_db

    await init_db()
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="Synthetic Researcher",
                researcher_email="r245@example.test",
                initial_request="synthetic",
                current_state="feasibility_validation",
            )
        )


async def _report_row(request_id):
    from sqlalchemy import select

    from app.database import FeasibilityReport, get_db_session

    async with get_db_session() as session:
        return (
            await session.execute(
                select(FeasibilityReport).where(FeasibilityReport.request_id == request_id)
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_a_rerun_that_loses_its_estimate_clears_the_saved_count():
    import uuid

    request_id = f"REQ-245-{uuid.uuid4().hex[:8].upper()}"
    await _seed_request(request_id)
    agent = PhenotypeValidationAgent()
    await agent._save_feasibility_report(
        request_id,
        {
            "feasible": True,
            "feasibility_score": 0.9,
            "estimated_cohort_size": 120,
            "confidence_interval": (102, 138),
        },
    )

    await agent._save_feasibility_report(
        request_id, dict(UNAVAILABLE_REPORT, feasible=False, confidence_interval=None)
    )

    row = await _report_row(request_id)
    assert row.estimated_cohort_size is None
    assert row.confidence_interval_low is None


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_workflow_persistence_saves_an_unavailable_estimate(existing):
    import uuid

    from app.langchain_orchestrator.persistence import WorkflowPersistence

    request_id = f"REQ-245-{uuid.uuid4().hex[:8].upper()}"
    await _seed_request(request_id)
    persistence = WorkflowPersistence()
    state = {
        "request_id": request_id,
        "current_state": "phenotype_review",
        "feasible": False,
        "feasibility_score": None,
        "estimated_cohort_size": None,
        "phenotype_sql": "SELECT 1",
        "updated_at": "2026-11-04T12:00:00",
    }
    if existing:
        await persistence.save_workflow_state(
            dict(state, feasible=True, feasibility_score=0.9, estimated_cohort_size=120)
        )

    await persistence.save_workflow_state(state)

    row = await _report_row(request_id)
    assert row.estimated_cohort_size is None
    assert row.is_feasible is False
