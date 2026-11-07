"""#245: the admin dashboard's G2 SQL review shows "estimate unavailable"
instead of a count, and renders without crashing on the missing numbers.

Drives the real ``display_sql_approval`` through ``streamlit.testing``.
"""

from streamlit.testing.v1 import AppTest

UNAVAILABLE = {
    "phenotype_sql": "SELECT COUNT(*) FROM sqlonfhir.patient_simple WHERE gender = :g",
    "estimated_cohort_size": None,
    "feasibility_score": None,
    "cohort_estimate": {"status": "unavailable", "error_ref": "abcdef123456"},
    "data_availability": {"overall_availability": 0.9},
    "estimated_extraction_time_hours": None,
    "auto_feasibility_assessment": "unavailable",
    "warnings": [
        {
            "type": "cohort_estimate_unavailable",
            "message": "Cohort estimate unavailable: the count query failed (ref: abcdef123456)",
        }
    ],
    "recommendations": [],
}


def _render(data):
    from app.web_ui.admin_dashboard import display_sql_approval

    display_sql_approval(data)


def _run(data):
    at = AppTest.from_function(_render, args=(data,), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def test_g2_shows_estimate_unavailable_not_a_count():
    at = _run(UNAVAILABLE)

    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Estimated Cohort"] == "Unavailable"
    assert metrics["Feasibility Score"] == "—"
    assert metrics["Est. Preview Time"] == "—"
    shown = " ".join(e.value for e in at.error)
    assert "abcdef123456" in shown
    assert "Low Cohort Size" not in shown


def test_a_workflow_failure_payload_without_estimate_status_still_says_unavailable():
    # The workflow's agent-failure path sets the status; an older payload may
    # only have the missing count.
    data = {k: v for k, v in UNAVAILABLE.items() if k != "cohort_estimate"}
    data["estimated_extraction_time_hours"] = 0
    at = _run(data)

    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Estimated Cohort"] == "Unavailable"


def test_a_real_estimate_still_shows_its_numbers():
    data = dict(
        UNAVAILABLE,
        estimated_cohort_size=12,
        feasibility_score=0.4,
        cohort_estimate={"status": "ok"},
        estimated_extraction_time_hours=2.5,
        auto_feasibility_assessment="not_feasible",
        warnings=[],
    )
    at = _run(data)

    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Estimated Cohort"] == "12"
    assert metrics["Feasibility Score"] == "0.40"
    assert metrics["Est. Preview Time"] == "2.5 hrs"


def _render_preview_qa(data):
    from app.web_ui.admin_dashboard import display_preview_qa_approval

    display_preview_qa_approval(data)


def test_the_preview_qa_view_without_an_estimate_shows_no_expected_range():
    from app.langchain_orchestrator.approval_bridge import ApprovalBridge

    data = ApprovalBridge._extract_approval_data(
        None, "preview_qa", {"estimated_cohort_size": None, "preview_package": {"cohort": []}}
    )
    at = AppTest.from_function(_render_preview_qa, args=(data,), default_timeout=30)
    at.run()

    assert not at.exception, at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Estimated Cohort"] == "Unavailable"
    assert metrics["Tolerance (±)"] == "—"
    assert not any("Expected Range" in i.value for i in at.info)
