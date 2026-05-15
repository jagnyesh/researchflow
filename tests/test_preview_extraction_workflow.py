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
from app.orchestrator.workflow_engine import WorkflowEngine


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
def workflow_engine():
    """Create workflow engine"""
    return WorkflowEngine()


@pytest.fixture
def sample_context():
    """Sample context for preview extraction"""
    return {
        "request_id": "REQ-20250104-12345",
        "requirements": {
            "data_elements": ["lab_results", "medications", "clinical_notes"],
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
        """Test that preview extraction calls preview method for each data element"""
        # Mock responses
        mock_sql_adapter.execute_sql.side_effect = [
            # Cohort query
            [{"patient_id": f"P{i}", "birthDate": "1970-01-01"} for i in range(50)],
            # Lab results (10 rows)
            [{"patient_id": "P1", "code": "GLU", "value": 95} for _ in range(10)],
            # Medications (10 rows)
            [{"patient_id": "P1", "medication": "Metformin"} for _ in range(10)],
            # Clinical notes (10 rows)
            [{"patient_id": "P1", "note_text": "Test note"} for _ in range(10)],
        ]

        result = await extraction_agent._extract_preview(sample_context)

        # Verify all data elements were extracted
        preview_data = result["preview_package"]["preview_data"]
        assert "lab_results" in preview_data
        assert "medications" in preview_data
        assert "clinical_notes" in preview_data

        # Verify each element has 10 rows
        assert len(preview_data["lab_results"]) == 10
        assert len(preview_data["medications"]) == 10
        assert len(preview_data["clinical_notes"]) == 10

    @pytest.mark.asyncio
    async def test_extract_preview_no_deidentification(
        self, extraction_agent, mock_sql_adapter, sample_context
    ):
        """Test that preview skips de-identification"""
        # Mock responses
        mock_sql_adapter.execute_sql.side_effect = [
            [{"patient_id": "P123", "birthDate": "1970-01-01"}],
            [{"patient_id": "P123", "patient_name": "John Doe", "ssn": "123-45-6789"}],
            [],
            [],
        ]

        result = await extraction_agent._extract_preview(sample_context)

        # Verify PHI is NOT removed (preview is internal review only)
        preview_data = result["preview_package"]["preview_data"]
        if preview_data.get("lab_results"):
            first_record = preview_data["lab_results"][0]
            # PHI should still be present (not de-identified)
            assert "patient_id" in first_record
            # Note: De-identification is skipped in preview, so PHI remains

    @pytest.mark.asyncio
    async def test_extract_data_element_preview_uses_limit_parameter(
        self, extraction_agent, mock_sql_adapter, sample_context
    ):
        """Test that preview extraction uses LIMIT parameter"""
        # Mock patient IDs
        patient_ids = [f"P{i}" for i in range(50)]
        time_period = {}

        # Call preview method
        await extraction_agent._extract_data_element_preview(
            data_element="lab_results",
            patient_ids=patient_ids,
            time_period=time_period,
            limit=10,
        )

        # Verify SQL was called
        assert mock_sql_adapter.execute_sql.called
        call_args = mock_sql_adapter.execute_sql.call_args

        # Verify params contain preview_limit
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


class TestWorkflowEnginePreviewTransitions:
    """Test suite for workflow engine preview state transitions"""

    def test_phenotype_approval_routes_to_preview_extraction(self, workflow_engine):
        """Test that phenotype approval routes to preview extraction"""
        result = workflow_engine.determine_next_step(
            completed_agent="approval_service",
            completed_task="approve_phenotype_sql",
            result={"approved": True},
        )

        assert result is not None
        assert result["next_agent"] == "extraction_agent"
        assert result["next_task"] == "extract_preview"
        assert result["next_state"] == WorkflowState.PREVIEW_EXTRACTION

    def test_preview_extraction_routes_to_preview_qa(self, workflow_engine):
        """Test that preview extraction routes to preview QA"""
        result = workflow_engine.determine_next_step(
            completed_agent="extraction_agent",
            completed_task="extract_preview",
            result={"preview_extracted": True},
        )

        assert result is not None
        assert result["next_agent"] == "qa_agent"
        assert result["next_task"] == "validate_preview"
        assert result["next_state"] == WorkflowState.PREVIEW_QA

    def test_preview_qa_passed_routes_to_full_extraction(self, workflow_engine):
        """Test that preview QA passed routes to full extraction"""
        result = workflow_engine.determine_next_step(
            completed_agent="qa_agent",
            completed_task="validate_preview",
            result={"preview_qa_passed": True},
        )

        assert result is not None
        assert result["next_agent"] == "extraction_agent"
        assert result["next_task"] == "extract_data"
        assert result["next_state"] == WorkflowState.DATA_EXTRACTION

    def test_preview_qa_failed_routes_to_human_review(self, workflow_engine):
        """Test that preview QA failed routes to human review"""
        result = workflow_engine.determine_next_step(
            completed_agent="qa_agent",
            completed_task="validate_preview_failed",
            result={"preview_qa_passed": False},
        )

        assert result is not None
        assert result["next_agent"] is None
        assert result["next_task"] is None
        assert result["next_state"] == WorkflowState.HUMAN_REVIEW

    def test_full_qa_passed_routes_to_delivery_review(self, workflow_engine):
        """Test that full QA passed routes to delivery review (not direct delivery)"""
        result = workflow_engine.determine_next_step(
            completed_agent="qa_agent",
            completed_task="validate_extracted_data",
            result={"overall_status": "passed"},
        )

        assert result is not None
        assert result["next_agent"] is None  # Waits for approval
        assert result["next_task"] is None
        assert result["next_state"] == WorkflowState.DELIVERY_REVIEW

    def test_delivery_approved_routes_to_delivery(self, workflow_engine):
        """Test that delivery approval routes to data delivery"""
        result = workflow_engine.determine_next_step(
            completed_agent="approval_service",
            completed_task="approve_delivery",
            result={"approved": True},
        )

        assert result is not None
        assert result["next_agent"] == "delivery_agent"
        assert result["next_task"] == "deliver_data"
        assert result["next_state"] == WorkflowState.DATA_DELIVERY

    def test_delivery_rejected_routes_to_reextraction(self, workflow_engine):
        """Test that delivery rejection routes back to extraction"""
        result = workflow_engine.determine_next_step(
            completed_agent="approval_service",
            completed_task="reject_delivery",
            result={"approved": False},
        )

        assert result is not None
        assert result["next_agent"] == "extraction_agent"
        assert result["next_task"] == "extract_data"
        assert result["next_state"] == WorkflowState.DATA_EXTRACTION

    def test_delivery_review_is_approval_state(self, workflow_engine):
        """Test that DELIVERY_REVIEW is recognized as approval state"""
        assert workflow_engine.is_approval_state(WorkflowState.DELIVERY_REVIEW)
        assert workflow_engine.get_approval_type(WorkflowState.DELIVERY_REVIEW) == "delivery"
        assert workflow_engine.get_approval_timeout_hours("delivery") == 24

    def test_preview_states_exist(self, workflow_engine):
        """Test that preview states exist in workflow engine"""
        # Verify states exist
        assert hasattr(WorkflowState, "PREVIEW_EXTRACTION")
        assert hasattr(WorkflowState, "PREVIEW_QA")
        assert hasattr(WorkflowState, "PREVIEW_COMPLETE")
        assert hasattr(WorkflowState, "DELIVERY_REVIEW")

        # Verify state descriptions exist
        assert workflow_engine.get_state_description(WorkflowState.PREVIEW_EXTRACTION)
        assert workflow_engine.get_state_description(WorkflowState.PREVIEW_QA)
        assert workflow_engine.get_state_description(WorkflowState.DELIVERY_REVIEW)


class TestEndToEndPreviewWorkflow:
    """End-to-end integration tests for preview workflow"""

    @pytest.mark.asyncio
    async def test_complete_preview_workflow_happy_path(
        self, extraction_agent, qa_agent, workflow_engine, sample_context, mock_sql_adapter
    ):
        """Test complete workflow: phenotype approval → preview → full extraction → delivery"""

        # Step 1: Phenotype approval → Preview extraction
        transition1 = workflow_engine.determine_next_step(
            completed_agent="approval_service",
            completed_task="approve_phenotype_sql",
            result={"approved": True},
        )
        assert transition1["next_state"] == WorkflowState.PREVIEW_EXTRACTION

        # Step 2: Execute preview extraction
        mock_sql_adapter.execute_sql.side_effect = [
            [{"patient_id": f"P{i}"} for i in range(50)],  # Cohort
            [{"patient_id": "P1", "code": "GLU"}] * 10,  # Lab results
            [{"patient_id": "P1", "drug": "Med1"}] * 10,  # Medications
            [{"patient_id": "P1", "note": "Note"}] * 10,  # Clinical notes
        ]

        preview_result = await extraction_agent._extract_preview(sample_context)
        assert preview_result["preview_extracted"] == True

        # Step 3: Preview extraction → Preview QA
        transition2 = workflow_engine.determine_next_step(
            completed_agent="extraction_agent",
            completed_task="extract_preview",
            result=preview_result,
        )
        assert transition2["next_state"] == WorkflowState.PREVIEW_QA

        # Step 4: Execute preview QA
        qa_context = {
            **sample_context,
            "preview_package": preview_result["preview_package"],
        }
        preview_qa_result = await qa_agent._validate_preview(qa_context)
        assert preview_qa_result["preview_qa_passed"] == True

        # Step 5: Preview QA passed → Full extraction
        transition3 = workflow_engine.determine_next_step(
            completed_agent="qa_agent",
            completed_task="validate_preview",
            result=preview_qa_result,
        )
        assert transition3["next_state"] == WorkflowState.DATA_EXTRACTION

        # Step 6: Full extraction → Full QA (simulate)
        # (Full extraction already tested elsewhere, skip here)

        # Step 7: Full QA passed → Delivery review
        transition4 = workflow_engine.determine_next_step(
            completed_agent="qa_agent",
            completed_task="validate_extracted_data",
            result={"overall_status": "passed"},
        )
        assert transition4["next_state"] == WorkflowState.DELIVERY_REVIEW

        # Step 8: Delivery approved → Data delivery
        transition5 = workflow_engine.determine_next_step(
            completed_agent="approval_service",
            completed_task="approve_delivery",
            result={"approved": True},
        )
        assert transition5["next_state"] == WorkflowState.DATA_DELIVERY

        print("✓ Complete preview workflow test passed")

    @pytest.mark.asyncio
    async def test_preview_workflow_failure_path(
        self, extraction_agent, qa_agent, workflow_engine, sample_context, mock_sql_adapter
    ):
        """Test workflow failure path: preview QA fails → human review"""

        # Step 1: Phenotype approval → Preview extraction
        transition1 = workflow_engine.determine_next_step(
            completed_agent="approval_service",
            completed_task="approve_phenotype_sql",
            result={"approved": True},
        )
        assert transition1["next_state"] == WorkflowState.PREVIEW_EXTRACTION

        # Step 2: Execute preview extraction (with empty data)
        mock_sql_adapter.execute_sql.side_effect = [
            [{"patient_id": f"P{i}"} for i in range(50)],  # Cohort
            [],  # Lab results - EMPTY
            [],  # Medications - EMPTY
            [],  # Clinical notes - EMPTY
        ]

        preview_result = await extraction_agent._extract_preview(sample_context)

        # Step 3: Execute preview QA (will fail)
        qa_context = {
            **sample_context,
            "preview_package": preview_result["preview_package"],
        }
        preview_qa_result = await qa_agent._validate_preview(qa_context)
        assert preview_qa_result["preview_qa_passed"] == False

        # Step 4: Preview QA failed → Human review
        transition2 = workflow_engine.determine_next_step(
            completed_agent="qa_agent",
            completed_task="validate_preview_failed",
            result=preview_qa_result,
        )
        assert transition2["next_state"] == WorkflowState.HUMAN_REVIEW

        print("✓ Preview workflow failure path test passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
