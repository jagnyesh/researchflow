"""
Tests for Preview Extraction Workflow

These tests verify that:
1. Extraction agent properly extracts preview data (10 rows per element)
2. QA agent validates preview data and auto-approves if checks pass
3. Workflow engine correctly transitions through preview states
4. End-to-end workflow: phenotype approval → preview → full extraction → delivery review

NOTE: These are unit tests with mocked components - no database required.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from app.agents.extraction_agent import DataExtractionAgent
from app.agents.qa_agent import QualityAssuranceAgent
from app.database.workflow_states import WorkflowState


@pytest.fixture
def mock_sql_adapter():
    """Mock SQL adapter for testing"""
    adapter = MagicMock()
    adapter.execute_sql = AsyncMock()
    return adapter


@pytest.fixture
def extraction_agent(mock_sql_adapter):
    """Create extraction agent with mocked SQL adapter"""
    agent = DataExtractionAgent()
    agent.sql_adapter = mock_sql_adapter
    return agent


@pytest.fixture
def qa_agent():
    """Create QA agent"""
    return QualityAssuranceAgent()


@pytest.fixture
def sample_context():
    """Sample context for preview extraction.

    Sprint 6.5b (#79): data_elements use the live demographic dispatch path
    (only path that reaches sql_adapter post-cleanup). The previous
    lab_results/medications/clinical_notes list exercised dead branches that
    silently failed in production; tests asserting their result shape were
    asserting dead-code behavior against a mocked adapter.
    """
    return {
        "request_id": "REQ-20250104-12345",
        "requirements": {
            "data_elements": ["family name", "given name", "date of birth"],
            "time_period": {"start": "2020-01-01", "end": "2023-12-31"},
            "phi_level": "de-identified",
            "delivery_format": "CSV",
        },
        "phenotype_sql": """
            SELECT patient_id, birthDate, gender
            FROM patient
            WHERE gender = 'female' AND age > 50
        """,
    }


class TestExtractionAgentPreview:
    """Test suite for extraction agent preview functionality"""

    @pytest.mark.asyncio
    async def test_extract_preview_returns_correct_structure(
        self, extraction_agent, mock_sql_adapter, sample_context
    ):
        """Test that extract_preview returns expected structure"""
        # Mock cohort query
        mock_sql_adapter.execute_sql.return_value = [
            {"patient_id": f"P{i}", "birthDate": "1970-01-01", "gender": "female"}
            for i in range(100)
        ]

        # Execute preview extraction
        result = await extraction_agent._extract_preview(sample_context)

        # Verify result structure
        assert result["preview_extracted"] == True
        assert "preview_package" in result
        assert result["next_agent"] == "qa_agent"
        assert result["next_task"] == "validate_preview"

        # Verify preview package structure
        preview_package = result["preview_package"]
        assert "cohort" in preview_package
        assert "preview_data" in preview_package
        assert "metadata" in preview_package
        assert preview_package["metadata"]["is_preview"] == True
        assert preview_package["metadata"]["preview_rows_per_element"] == 10

    @pytest.mark.asyncio
    async def test_extract_preview_limits_cohort_to_10(
        self, extraction_agent, mock_sql_adapter, sample_context
    ):
        """Test that preview limits cohort to 10 patients"""
        # Mock cohort with 100 patients
        mock_cohort = [
            {"patient_id": f"P{i}", "birthDate": "1970-01-01", "gender": "female"}
            for i in range(100)
        ]
        mock_sql_adapter.execute_sql.return_value = mock_cohort

        result = await extraction_agent._extract_preview(sample_context)

        preview_package = result["preview_package"]
        # Preview cohort should be limited to 10
        assert len(preview_package["cohort"]) == 10
        # But metadata should show total cohort size
        assert preview_package["metadata"]["cohort_size"] == 100

    @pytest.mark.asyncio
    async def test_extract_preview_calls_preview_method_for_each_element(
        self, extraction_agent, mock_sql_adapter, sample_context
    ):
        """Verify the preview loop dispatches _extract_data_element_preview
        for each requested data element. Sample_context uses the demographic
        live-dispatch keys (see fixture docstring)."""
        mock_sql_adapter.execute_sql.side_effect = [
            # Cohort query
            [{"patient_id": f"P{i}", "birthDate": "1970-01-01"} for i in range(50)],
            # family name (10 rows)
            [{"patient_id": "P1", "family_name": "Doe"} for _ in range(10)],
            # given name (10 rows)
            [{"patient_id": "P1", "given_name": "Jane"} for _ in range(10)],
            # date of birth (10 rows)
            [{"patient_id": "P1", "birth_date": "1970-01-01"} for _ in range(10)],
        ]

        result = await extraction_agent._extract_preview(sample_context)

        preview_data = result["preview_package"]["preview_data"]
        assert "family name" in preview_data
        assert "given name" in preview_data
        assert "date of birth" in preview_data

        assert len(preview_data["family name"]) == 10
        assert len(preview_data["given name"]) == 10
        assert len(preview_data["date of birth"]) == 10

    @pytest.mark.asyncio
    async def test_extract_preview_no_deidentification(
        self, extraction_agent, mock_sql_adapter, sample_context
    ):
        """Preview is internal-review-only; PHI should remain in the result
        even though phi_level=de-identified. Verified against the live
        demographic dispatch path."""
        mock_sql_adapter.execute_sql.side_effect = [
            [{"patient_id": "P123", "birthDate": "1970-01-01"}],  # cohort
            [{"patient_id": "P123", "family_name": "Doe"}],  # family name
            [{"patient_id": "P123", "given_name": "Jane"}],  # given name
            [{"patient_id": "P123", "birth_date": "1970-01-01"}],  # date of birth
        ]

        result = await extraction_agent._extract_preview(sample_context)

        preview_data = result["preview_package"]["preview_data"]
        # PHI must remain in preview (researcher inspects raw data pre-delivery)
        assert preview_data["family name"], "expected demographic rows to flow through"
        first_record = preview_data["family name"][0]
        assert "patient_id" in first_record
        assert "family_name" in first_record

    @pytest.mark.asyncio
    async def test_extract_data_element_preview_demographics_uses_limit(
        self, extraction_agent, mock_sql_adapter, sample_context
    ):
        """Sprint 6.5b (#79): preview extraction's only live dispatch path is
        the demographics branch against sqlonfhir.patient_demographics.
        Verify preview_limit gets bound when a demographic data element is
        requested. Non-demographic data elements take the early-return path
        and never reach sql_adapter."""
        patient_ids = [f"P{i}" for i in range(50)]
        time_period = {}

        await extraction_agent._extract_data_element_preview(
            data_element="family name",
            patient_ids=patient_ids,
            time_period=time_period,
            limit=10,
        )

        assert mock_sql_adapter.execute_sql.called
        call_args = mock_sql_adapter.execute_sql.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        assert params.get("preview_limit") == 10


class TestQAAgentPreview:
    """Test suite for QA agent preview validation"""

    @pytest.mark.asyncio
    async def test_validate_preview_passes_with_valid_data(self, qa_agent):
        """Test that preview QA passes with valid preview data"""
        context = {
            "request_id": "REQ-20250104-12345",
            "requirements": {
                "data_elements": ["lab_results", "medications"],
            },
            "preview_package": {
                "cohort": [{"patient_id": f"P{i}"} for i in range(10)],
                "preview_data": {
                    "lab_results": [{"patient_id": "P1", "code": "GLU"} for _ in range(10)],
                    "medications": [{"patient_id": "P1", "drug": "Med1"} for _ in range(10)],
                },
                "metadata": {"cohort_size": 100},
            },
        }

        result = await qa_agent._validate_preview(context)

        # Verify auto-approval
        assert result["preview_qa_passed"] == True
        assert result["next_agent"] == "extraction_agent"
        assert result["next_task"] == "extract_data"
        assert "qa_report" in result
        assert result["qa_report"]["overall_status"] == "passed"

    @pytest.mark.asyncio
    async def test_validate_preview_fails_with_missing_elements(self, qa_agent):
        """Test that preview QA fails when data elements are missing"""
        context = {
            "request_id": "REQ-20250104-12345",
            "requirements": {
                "data_elements": ["lab_results", "medications", "clinical_notes"],
            },
            "preview_package": {
                "cohort": [{"patient_id": f"P{i}"} for i in range(10)],
                "preview_data": {
                    "lab_results": [{"patient_id": "P1"} for _ in range(10)],
                    # medications and clinical_notes are MISSING
                },
                "metadata": {"cohort_size": 100},
            },
        }

        result = await qa_agent._validate_preview(context)

        # Verify failure
        assert result["preview_qa_passed"] == False
        assert result["next_agent"] is None
        assert "qa_report" in result
        assert result["qa_report"]["overall_status"] == "failed"

    @pytest.mark.asyncio
    async def test_validate_preview_fails_with_empty_data(self, qa_agent):
        """Test that preview QA fails when data elements are empty"""
        context = {
            "request_id": "REQ-20250104-12345",
            "requirements": {
                "data_elements": ["lab_results"],
            },
            "preview_package": {
                "cohort": [{"patient_id": f"P{i}"} for i in range(10)],
                "preview_data": {
                    "lab_results": [],  # EMPTY
                },
                "metadata": {"cohort_size": 100},
            },
        }

        result = await qa_agent._validate_preview(context)

        # Verify failure
        assert result["preview_qa_passed"] == False
        assert result["qa_report"]["overall_status"] == "failed"

    @pytest.mark.asyncio
    async def test_validate_preview_fails_with_empty_cohort(self, qa_agent):
        """Test that preview QA fails when cohort is empty"""
        context = {
            "request_id": "REQ-20250104-12345",
            "requirements": {
                "data_elements": ["lab_results"],
            },
            "preview_package": {
                "cohort": [],  # EMPTY COHORT
                "preview_data": {
                    "lab_results": [{"patient_id": "P1"} for _ in range(10)],
                },
                "metadata": {"cohort_size": 0},
            },
        }

        result = await qa_agent._validate_preview(context)

        # Verify failure
        assert result["preview_qa_passed"] == False

    @pytest.mark.asyncio
    async def test_validate_preview_checks_are_simplified(self, qa_agent):
        """Test that preview QA runs simplified checks (no de-identification check)"""
        context = {
            "request_id": "REQ-20250104-12345",
            "requirements": {
                "data_elements": ["lab_results"],
            },
            "preview_package": {
                "cohort": [{"patient_id": f"P{i}"} for i in range(10)],
                "preview_data": {
                    "lab_results": [
                        {"patient_id": "P1", "patient_name": "John Doe"}  # PHI present
                        for _ in range(10)
                    ],
                },
                "metadata": {"cohort_size": 100},
            },
        }

        result = await qa_agent._validate_preview(context)

        # Verify passes even with PHI (de-identification check skipped)
        assert result["preview_qa_passed"] == True
        qa_report = result["qa_report"]

        # Verify only 3 checks (no de-identification check)
        check_names = [check["check_name"] for check in qa_report["checks"]]
        assert "preview_completeness" in check_names
        assert "preview_data_quality" in check_names
        assert "preview_cohort_validation" in check_names
        assert "deidentification" not in check_names


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
