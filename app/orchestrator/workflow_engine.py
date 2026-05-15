"""
Workflow Engine for ResearchFlow

Manages workflow state transitions and routing logic between agents.
"""

from typing import Dict, Any, Optional, Callable
from datetime import datetime
import logging

# Sprint 7.2 Phase 0: WorkflowState was promoted to app/database/workflow_states.py
# (it's effectively the DB schema enum for research_requests.current_state, used
# by 5 production callers). The re-export below keeps A2A's internal
# self-references working until Sprint 7.2 Phase 4 deletes app/orchestrator/
# entirely. Both import paths resolve to the SAME enum object; there is no
# parallel definition and no value drift risk.
from app.database.workflow_states import WorkflowState  # noqa: F401

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    State machine for managing research request workflows
    """

    def __init__(self):
        self.workflow_rules = self._define_workflow_rules()

    def _define_workflow_rules(self) -> Dict[tuple, Dict]:
        """
        Define workflow transition rules

        Format: (current_agent, current_task) -> {condition, next_agent, next_task}
        """
        return {
            # Requirements gathering - multiple outcomes based on completeness and approval needs
            ("requirements_agent", "gather_requirements"): [
                {
                    # Requirements complete AND needs approval -> Requirements Review (conversational mode)
                    "condition": lambda r: r.get("requirements_complete") == True
                    and r.get("requires_approval") == True,
                    "next_agent": None,  # Wait for approval
                    "next_task": None,
                    "next_state": WorkflowState.REQUIREMENTS_REVIEW,
                },
                {
                    # Requirements complete AND NO approval needed -> Phenotype Agent (form-based mode)
                    # Skip requirements review, go straight to SQL generation (SQL will be reviewed instead)
                    "condition": lambda r: r.get("requirements_complete") == True
                    and r.get("requires_approval") == False,
                    "next_agent": "phenotype_agent",  # Trigger phenotype agent immediately
                    "next_task": "validate_feasibility",
                    "next_state": WorkflowState.FEASIBILITY_VALIDATION,
                },
                {
                    # Requirements incomplete -> Continue gathering (conversational loop)
                    "condition": lambda r: r.get("requirements_complete") == False,
                    "next_agent": "requirements_agent",
                    "next_task": "gather_requirements",
                    "next_state": WorkflowState.REQUIREMENTS_GATHERING,
                },
            ],
            # Requirements approved -> Phenotype validation
            ("approval_service", "approve_requirements"): {
                "condition": lambda r: r.get("approved") == True,
                "next_agent": "phenotype_agent",
                "next_task": "validate_feasibility",
                "next_state": WorkflowState.FEASIBILITY_VALIDATION,
            },
            # Requirements rejected -> Back to requirements gathering
            ("approval_service", "reject_requirements"): {
                "condition": lambda r: r.get("approved") == False,
                "next_agent": "requirements_agent",
                "next_task": "gather_requirements",
                "next_state": WorkflowState.REQUIREMENTS_GATHERING,
            },
            # Phenotype validation complete -> ALWAYS go to SQL review
            # The phenotype agent generates SQL and metrics, but the informatician
            # decides whether the SQL is appropriate to run (regardless of cohort size)
            ("phenotype_agent", "validate_feasibility"): {
                "condition": lambda r: True,  # Always proceed to review
                "next_agent": None,  # Waits for informatician SQL approval
                "next_task": None,
                "next_state": WorkflowState.PHENOTYPE_REVIEW,
            },
            # Phenotype SQL approved -> Preview extraction (NEW FLOW)
            ("approval_service", "approve_phenotype_sql"): {
                "condition": lambda r: r.get("approved") == True,
                "next_agent": "extraction_agent",
                "next_task": "extract_preview",
                "next_state": WorkflowState.PREVIEW_EXTRACTION,
            },
            # Phenotype SQL rejected -> Back to phenotype agent
            ("approval_service", "reject_phenotype_sql"): {
                "condition": lambda r: r.get("approved") == False,
                "next_agent": "phenotype_agent",
                "next_task": "validate_feasibility",
                "next_state": WorkflowState.FEASIBILITY_VALIDATION,
            },
            # Preview extraction complete -> Preview QA (NEW)
            ("extraction_agent", "extract_preview"): {
                "condition": lambda r: r.get("preview_extracted") == True,
                "next_agent": "qa_agent",
                "next_task": "validate_preview",
                "next_state": WorkflowState.PREVIEW_QA,
            },
            # Preview QA validation -> Route based on outcome (NEW)
            ("qa_agent", "validate_preview"): [
                {
                    # Preview passed -> Full extraction
                    "condition": lambda r: r.get("preview_qa_passed") == True,
                    "next_agent": "extraction_agent",
                    "next_task": "extract_data",
                    "next_state": WorkflowState.DATA_EXTRACTION,
                },
                {
                    # Preview failed -> Wait for approval (requires_approval will be True)
                    "condition": lambda r: r.get("preview_qa_passed") == False
                    and r.get("requires_approval") == True,
                    "next_agent": None,
                    "next_task": None,
                    "next_state": WorkflowState.HUMAN_REVIEW,
                },
            ],
            # Preview QA approved -> Proceed to full extraction despite mismatch (NEW)
            ("approval_service", "approve_preview_qa"): {
                "condition": lambda r: r.get("approved") == True,
                "next_agent": "extraction_agent",
                "next_task": "extract_data",
                "next_state": WorkflowState.DATA_EXTRACTION,
            },
            # Preview QA rejected -> Return to phenotype agent for SQL revision (NEW)
            ("approval_service", "reject_preview_qa"): {
                "condition": lambda r: r.get("approved") == False,
                "next_agent": "phenotype_agent",
                "next_task": "validate_feasibility",
                "next_state": WorkflowState.FEASIBILITY_VALIDATION,
            },
            # Kickoff meeting scheduled -> Extraction Approval (LEGACY - OPTIONAL POST-DELIVERY)
            ("calendar_agent", "schedule_kickoff_meeting"): {
                "condition": lambda r: r.get("meeting_scheduled") == True,
                "next_agent": None,  # Waits for extraction approval
                "next_task": None,
                "next_state": WorkflowState.EXTRACTION_APPROVAL,
            },
            # Extraction approved -> Data extraction
            ("approval_service", "approve_extraction"): {
                "condition": lambda r: r.get("approved") == True,
                "next_agent": "extraction_agent",
                "next_task": "extract_data",
                "next_state": WorkflowState.DATA_EXTRACTION,
            },
            # Extraction rejected -> Human review
            ("approval_service", "reject_extraction"): {
                "condition": lambda r: r.get("approved") == False,
                "next_agent": None,
                "next_task": None,
                "next_state": WorkflowState.HUMAN_REVIEW,
            },
            # Data extraction complete -> QA validation
            ("extraction_agent", "extract_data"): {
                "condition": lambda r: r.get("extraction_complete") == True,
                "next_agent": "qa_agent",
                "next_task": "validate_extracted_data",
                "next_state": WorkflowState.QA_VALIDATION,
            },
            # QA passed -> Delivery Review (UPDATED - Informatician reviews full dataset)
            ("qa_agent", "validate_extracted_data"): {
                "condition": lambda r: r.get("overall_status") == "passed",
                "next_agent": None,  # Waits for delivery approval
                "next_task": None,
                "next_state": WorkflowState.DELIVERY_REVIEW,
            },
            # Delivery review approved -> Data delivery (NEW)
            ("approval_service", "approve_delivery"): {
                "condition": lambda r: r.get("approved") == True,
                "next_agent": "delivery_agent",
                "next_task": "deliver_data",
                "next_state": WorkflowState.DATA_DELIVERY,
            },
            # Delivery review rejected -> Back to extraction (NEW)
            ("approval_service", "reject_delivery"): {
                "condition": lambda r: r.get("approved") == False,
                "next_agent": "extraction_agent",
                "next_task": "extract_data",
                "next_state": WorkflowState.DATA_EXTRACTION,
            },
            # QA approved -> Data delivery (LEGACY - kept for backwards compatibility)
            ("approval_service", "approve_qa"): {
                "condition": lambda r: r.get("approved") == True,
                "next_agent": "delivery_agent",
                "next_task": "deliver_data",
                "next_state": WorkflowState.DATA_DELIVERY,
            },
            # QA rejected -> Back to extraction (LEGACY - kept for backwards compatibility)
            ("approval_service", "reject_qa"): {
                "condition": lambda r: r.get("approved") == False,
                "next_agent": "extraction_agent",
                "next_task": "extract_data",
                "next_state": WorkflowState.DATA_EXTRACTION,
            },
            # QA failed -> Human review
            ("qa_agent", "validate_extracted_data_failed"): {
                "condition": lambda r: r.get("overall_status") == "failed",
                "next_agent": None,
                "next_task": None,
                "next_state": WorkflowState.QA_FAILED,
            },
            # Data delivered -> Complete
            ("delivery_agent", "deliver_data"): {
                "condition": lambda r: r.get("delivered") == True,
                "next_agent": None,
                "next_task": None,
                "next_state": WorkflowState.COMPLETE,
            },
            # Scope change workflows - can be triggered from any state
            ("coordinator_agent", "handle_scope_change"): {
                "condition": lambda r: r.get("scope_approved") == True,
                "next_agent": "requirements_agent",
                "next_task": "gather_requirements",
                "next_state": WorkflowState.REQUIREMENTS_GATHERING,
            },
            ("coordinator_agent", "reject_scope_change"): {
                "condition": lambda r: r.get("scope_approved") == False,
                "next_agent": None,
                "next_task": None,
                "next_state": WorkflowState.HUMAN_REVIEW,
            },
        }

    def determine_next_step(
        self, completed_agent: str, completed_task: str, result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Determine next workflow step based on current state and results

        Args:
            completed_agent: ID of agent that just completed
            completed_task: Task that was completed
            result: Result dictionary from the task

        Returns:
            Dict with next_agent, next_task, next_state or None if workflow complete
        """
        rule_key = (completed_agent, completed_task)
        rule = self.workflow_rules.get(rule_key)

        if not rule:
            logger.warning(f"No workflow rule found for {rule_key}")
            return None

        # Support both single rule (dict) and multiple rules (list of dicts)
        rules_to_check = rule if isinstance(rule, list) else [rule]

        # Check each condition in order
        for single_rule in rules_to_check:
            try:
                if single_rule["condition"](result):
                    next_step = {
                        "next_agent": single_rule["next_agent"],
                        "next_task": single_rule["next_task"],
                        "next_state": single_rule["next_state"],
                    }
                    logger.info(
                        f"Workflow transition: {completed_agent}.{completed_task} -> {next_step['next_agent']}.{next_step['next_task']} (state: {next_step['next_state'].value})"
                    )
                    return next_step
            except Exception as e:
                logger.error(f"Error evaluating workflow condition for {rule_key}: {e}")
                continue

        logger.warning(
            f"No workflow condition matched for {rule_key}. Result keys: {result.keys()}"
        )
        return None

    def get_initial_state(self) -> WorkflowState:
        """Get initial workflow state for new requests"""
        return WorkflowState.NEW_REQUEST

    def is_terminal_state(self, state: WorkflowState) -> bool:
        """Check if state is terminal (workflow complete)"""
        terminal_states = [
            WorkflowState.COMPLETE,
            WorkflowState.FAILED,
            WorkflowState.NOT_FEASIBLE,
            WorkflowState.QA_FAILED,
        ]
        return state in terminal_states

    def is_approval_state(self, state: WorkflowState) -> bool:
        """
        Check if state requires human approval

        Returns:
            True if state is an approval/review state
        """
        approval_states = [
            WorkflowState.REQUIREMENTS_REVIEW,
            WorkflowState.PHENOTYPE_REVIEW,
            WorkflowState.EXTRACTION_APPROVAL,
            WorkflowState.DELIVERY_REVIEW,  # NEW: Replaced QA_REVIEW
            WorkflowState.SCOPE_CHANGE,
            WorkflowState.HUMAN_REVIEW,
        ]
        return state in approval_states

    def get_approval_type(self, state: WorkflowState) -> Optional[str]:
        """
        Get the approval type for a given state

        Returns:
            Approval type string or None if not an approval state
        """
        approval_types = {
            WorkflowState.REQUIREMENTS_REVIEW: "requirements",
            WorkflowState.PHENOTYPE_REVIEW: "phenotype_sql",
            WorkflowState.EXTRACTION_APPROVAL: "extraction",
            WorkflowState.DELIVERY_REVIEW: "delivery",  # NEW: Replaced qa
            WorkflowState.SCOPE_CHANGE: "scope_change",
        }
        return approval_types.get(state)

    def get_approval_timeout_hours(self, approval_type: str) -> int:
        """
        Get timeout hours for each approval type

        Returns:
            Number of hours before approval times out
        """
        timeout_config = {
            "requirements": 24,
            "phenotype_sql": 24,  # Critical - SQL must be reviewed
            "extraction": 12,
            "delivery": 24,  # NEW: Critical - Full dataset must be reviewed before delivery
            "scope_change": 48,
        }
        return timeout_config.get(approval_type, 24)  # Default 24 hours

    def get_state_description(self, state: WorkflowState) -> str:
        """Get human-readable description of workflow state"""
        descriptions = {
            WorkflowState.NEW_REQUEST: "New request received",
            WorkflowState.REQUIREMENTS_GATHERING: "Gathering requirements from researcher",
            WorkflowState.REQUIREMENTS_COMPLETE: "Requirements complete, validating feasibility",
            # Approval state descriptions
            WorkflowState.REQUIREMENTS_REVIEW: "Waiting for informatician to review requirements",
            WorkflowState.PHENOTYPE_REVIEW: "Waiting for informatician to approve SQL query",
            WorkflowState.EXTRACTION_APPROVAL: "Waiting for approval to extract data",
            WorkflowState.DELIVERY_REVIEW: "Waiting for informatician to review and approve full dataset for delivery",
            WorkflowState.SCOPE_CHANGE: "Scope change requested, waiting for review",
            # Preview extraction state descriptions (NEW)
            WorkflowState.PREVIEW_EXTRACTION: "Extracting preview data (10 rows per data element)",
            WorkflowState.PREVIEW_QA: "Running QA validation on preview data",
            WorkflowState.PREVIEW_COMPLETE: "Preview validated and approved",
            WorkflowState.FEASIBILITY_VALIDATION: "Checking data availability and feasibility",
            WorkflowState.FEASIBLE: "Request is feasible, scheduling kickoff",
            WorkflowState.NOT_FEASIBLE: "Request not feasible with current criteria",
            WorkflowState.SCHEDULE_KICKOFF: "Scheduling kickoff meeting",
            WorkflowState.KICKOFF_COMPLETE: "Kickoff complete, starting extraction",
            WorkflowState.DATA_EXTRACTION: "Extracting data from sources",
            WorkflowState.EXTRACTION_COMPLETE: "Extraction complete, validating quality",
            WorkflowState.QA_VALIDATION: "Running quality assurance checks",
            WorkflowState.QA_PASSED: "QA passed, preparing delivery",
            WorkflowState.QA_FAILED: "QA failed, needs human review",
            WorkflowState.DATA_DELIVERY: "Packaging and delivering data",
            WorkflowState.DELIVERED: "Data delivered to researcher",
            WorkflowState.COMPLETE: "Request complete",
            WorkflowState.FAILED: "Request failed",
            WorkflowState.HUMAN_REVIEW: "Escalated to human review",
        }
        return descriptions.get(state, state.value)
