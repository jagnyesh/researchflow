"""
Integration test for workflow handling of incomplete requirements

Verifies that when requirements_complete is False, the workflow:
1. Does NOT mark the request as complete
2. Continues in requirements_gathering state
3. Returns to requirements_agent for continued conversation
"""

import pytest
from app.orchestrator.workflow_engine import WorkflowEngine, WorkflowState


class TestIncompleteRequirementsWorkflow:
    """Test workflow behavior when requirements are incomplete"""

    def setup_method(self):
        """Setup test fixtures"""
        self.workflow_engine = WorkflowEngine()

    def test_incomplete_requirements_continues_gathering(self):
        """Test that incomplete requirements continue the conversation"""
        # Simulate requirements agent result with incomplete requirements
        result = {
            "requirements_complete": False,
            "extracted_requirements": {
                "inclusion_criteria": ["diabetes"],
                "time_period": "past 2 years",
            },
            "missing_fields": ["irb_number", "data_elements"],
            "completeness_score": 0.67,
            "next_question": "What specific data elements do you need?",
        }

        # Determine next step
        next_step = self.workflow_engine.determine_next_step(
            completed_agent="requirements_agent",
            completed_task="gather_requirements",
            result=result,
        )

        # Assertions
        assert next_step is not None, "Next step should not be None for incomplete requirements"
        assert (
            next_step["next_agent"] == "requirements_agent"
        ), "Should continue with requirements agent"
        assert (
            next_step["next_task"] == "gather_requirements"
        ), "Should continue gathering requirements"
        assert (
            next_step["next_state"] == WorkflowState.REQUIREMENTS_GATHERING
        ), "Should stay in gathering state"

    def test_complete_requirements_goes_to_review(self):
        """Test that complete requirements move to review state (conversational mode)"""
        # Simulate requirements agent result with complete requirements AND approval needed
        result = {
            "requirements_complete": True,
            "requires_approval": True,  # Conversational mode requires approval
            "extracted_requirements": {
                "inclusion_criteria": ["diabetes"],
                "exclusion_criteria": ["pregnancy"],
                "time_period": "past 2 years",
                "data_elements": ["demographics", "lab_results"],
                "irb_number": "IRB-2025-001",
                "phi_level": "limited_dataset",
            },
            "completeness_score": 1.0,
            "approval_request": True,
        }

        # Determine next step
        next_step = self.workflow_engine.determine_next_step(
            completed_agent="requirements_agent",
            completed_task="gather_requirements",
            result=result,
        )

        # Assertions
        assert next_step is not None, "Next step should not be None for complete requirements"
        assert next_step["next_agent"] is None, "Should pause for approval, no next agent"
        assert next_step["next_task"] is None, "Should pause for approval, no next task"
        assert (
            next_step["next_state"] == WorkflowState.REQUIREMENTS_REVIEW
        ), "Should move to review state"

    def test_workflow_supports_multiple_conditions(self):
        """Test that workflow engine supports multiple conditions per rule"""
        rule_key = ("requirements_agent", "gather_requirements")
        rule = self.workflow_engine.workflow_rules.get(rule_key)

        # Assert rule exists and is a list (multiple conditions)
        assert rule is not None, "Rule should exist for requirements gathering"
        assert isinstance(rule, list), "Rule should be a list of conditions"
        assert (
            len(rule) >= 3
        ), "Should have at least 3 conditions (complete+approval, complete+no approval, incomplete)"

        # Assert first condition is for complete requirements WITH approval needed (conversational mode)
        assert rule[0]["condition"](
            {"requirements_complete": True, "requires_approval": True}
        ), "First condition should match complete=True and requires_approval=True"
        assert (
            rule[0]["next_state"] == WorkflowState.REQUIREMENTS_REVIEW
        ), "Complete with approval should go to review"

        # Assert second condition is for complete requirements WITHOUT approval (form-based mode)
        assert rule[1]["condition"](
            {"requirements_complete": True, "requires_approval": False}
        ), "Second condition should match complete=True and requires_approval=False"
        assert (
            rule[1]["next_state"] == WorkflowState.FEASIBILITY_VALIDATION
        ), "Complete without approval should go to phenotype"

        # Assert third condition is for incomplete requirements
        assert rule[2]["condition"](
            {"requirements_complete": False}
        ), "Third condition should match complete=False"
        assert (
            rule[2]["next_state"] == WorkflowState.REQUIREMENTS_GATHERING
        ), "Incomplete should stay in gathering"

    def test_phenotype_always_goes_to_review(self):
        """Test that phenotype agent ALWAYS requests informatician review"""
        rule_key = ("phenotype_agent", "validate_feasibility")
        rule = self.workflow_engine.workflow_rules.get(rule_key)

        # Assert rule exists and is a dict (single rule, not list)
        assert rule is not None, "Rule should exist for phenotype validation"
        assert isinstance(rule, dict), "Rule should be a dict (single rule)"
        assert not isinstance(rule, list), "Rule should NOT be a list - should always go to review"

        # Assert condition accepts ANY result (always returns True)
        assert rule["condition"]({"feasible": True}), "Should accept feasible=True"
        assert rule["condition"]({"feasible": False}), "Should accept feasible=False"
        assert rule["condition"]({}), "Should accept empty result"

        # Assert always goes to PHENOTYPE_REVIEW (informatician decides feasibility)
        assert (
            rule["next_state"] == WorkflowState.PHENOTYPE_REVIEW
        ), "Should always go to phenotype review"
        assert rule["next_agent"] is None, "Should wait for approval"
        assert rule["next_task"] is None, "Should wait for approval"

    def test_terminal_states_are_correct(self):
        """Test that workflow engine correctly identifies terminal states"""
        # Terminal states
        assert self.workflow_engine.is_terminal_state(WorkflowState.COMPLETE) is True
        assert self.workflow_engine.is_terminal_state(WorkflowState.FAILED) is True
        assert self.workflow_engine.is_terminal_state(WorkflowState.NOT_FEASIBLE) is True
        assert self.workflow_engine.is_terminal_state(WorkflowState.QA_FAILED) is True

        # Non-terminal states
        assert self.workflow_engine.is_terminal_state(WorkflowState.REQUIREMENTS_GATHERING) is False
        assert self.workflow_engine.is_terminal_state(WorkflowState.REQUIREMENTS_REVIEW) is False
        assert self.workflow_engine.is_terminal_state(WorkflowState.NEW_REQUEST) is False

    def test_approval_states_are_correct(self):
        """Test that workflow engine correctly identifies approval states"""
        # Approval states
        assert self.workflow_engine.is_approval_state(WorkflowState.REQUIREMENTS_REVIEW) is True
        assert self.workflow_engine.is_approval_state(WorkflowState.PHENOTYPE_REVIEW) is True
        assert self.workflow_engine.is_approval_state(WorkflowState.QA_REVIEW) is True
        assert self.workflow_engine.is_approval_state(WorkflowState.EXTRACTION_APPROVAL) is True

        # Non-approval states
        assert self.workflow_engine.is_approval_state(WorkflowState.REQUIREMENTS_GATHERING) is False
        assert self.workflow_engine.is_approval_state(WorkflowState.FEASIBILITY_VALIDATION) is False
        assert self.workflow_engine.is_approval_state(WorkflowState.COMPLETE) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
