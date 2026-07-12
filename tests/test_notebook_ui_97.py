"""Sprint 6.7 #97 — notebook UI: honest-error card + batch_anchor_ts disclosure.

The pure pieces are unit-tested here (validator touched_views, service anchor
wiring, the UI markdown helpers); the live Streamlit rendering is browser-QA'd
in the PR.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.feasibility_service import FeasibilityService
from app.services.schema_introspection import ColumnInfo, ViewSchema
from app.services.sql_synthesis import SynthesisResult
from app.services.sql_validator import SQLValidator
from app.web_ui.research_notebook import _error_card_markdown, _freshness_caption

CANNED_SCHEMAS = {
    "patient_demographics": ViewSchema(
        name="patient_demographics",
        description="",
        columns=(ColumnInfo("patient_id", "text"), ColumnInfo("gender", "text")),
    ),
    "condition_simple": ViewSchema(
        name="condition_simple",
        description="",
        columns=(ColumnInfo("patient_id", "text"), ColumnInfo("code_text", "text")),
    ),
}


class TestValidatorTouchedViews:
    def test_reports_the_sqlonfhir_views_a_query_reads(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p "
            "JOIN sqlonfhir.condition_simple c ON c.patient_id = p.patient_id "
            "WHERE p.gender = 'female'"
        )
        assert result.valid is True
        assert result.touched_views == ["condition_simple", "patient_demographics"]

    def test_empty_on_rejection(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT family_name FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False
        assert result.touched_views == []


class TestServiceAnchorWiring:
    async def test_success_variant_includes_batch_anchor_ts(self, monkeypatch):
        monkeypatch.setenv("USE_LLM_SQL_SYNTHESIS", "true")
        monkeypatch.setenv("EXPLORATORY_DB_URL", "postgresql://rf_readonly:x@localhost:5433/hapi")
        fs = FeasibilityService()
        fs.exploratory_db_client = MagicMock()
        fs.exploratory_db_client.execute_query = AsyncMock(return_value=[{"count": 9}])
        anchor = datetime(2026, 7, 12, 3, 0, 0)

        synth = MagicMock()
        synth.synthesize = AsyncMock(
            return_value=SynthesisResult(
                sql="SELECT COUNT(DISTINCT patient_id) FROM sqlonfhir.patient_demographics",
                explanation="counts patients",
            )
        )
        with (
            patch("app.services.feasibility_service.SQLSynthesizer", return_value=synth),
            patch(
                "app.services.feasibility_service.get_cached_schemas",
                new=AsyncMock(return_value=CANNED_SCHEMAS),
            ),
            patch.object(
                FeasibilityService, "_batch_anchor_for", new=AsyncMock(return_value=anchor)
            ),
        ):
            result = await fs.execute_feasibility_check(
                {"view_definitions": []}, natural_language_query="how many patients?"
            )

        assert result["status"] == "ok"
        assert result["estimated_cohort"] == 9
        assert result["batch_anchor_ts"] == anchor.isoformat()


class TestUIHelpers:
    def test_freshness_caption_formats_iso_anchor(self):
        cap = _freshness_caption({"batch_anchor_ts": "2026-07-12T03:00:00"})
        assert "Data as of 2026-07-12 03:00:00" in cap

    def test_freshness_caption_empty_without_anchor(self):
        assert _freshness_caption({"batch_anchor_ts": None}) == ""
        assert _freshness_caption({}) == ""

    def test_error_card_never_shows_a_cohort_count(self):
        md = _error_card_markdown(
            {
                "status": "error",
                "explanation": "counts diabetic patients",
                "reason": "output column 'family_name' is neither an aggregate nor a dimension",
                "rejected_sql": "SELECT family_name FROM sqlonfhir.patient_demographics",
            }
        )
        # The #76 invariant, at the UI layer: no fabricated cohort number.
        assert "estimated_cohort" not in md
        assert "0 patients" not in md
        assert "family_name" in md  # the rejected SQL + reason are shown
        assert "counts diabetic patients" in md
