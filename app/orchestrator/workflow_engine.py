"""
Workflow Engine for ResearchFlow

Manages workflow state transitions and routing logic between agents.
"""

from enum import Enum
from typing import Dict, Any, Optional, Callable
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class WorkflowState(Enum):
    """Workflow states for research data requests"""
    NEW_REQUEST = "new_request"
    REQUIREMENTS_GATHERING = "requirements_gathering"
    REQUIREMENTS_COMPLETE = "requirements_complete"

    # NEW APPROVAL STATES - Human-in-Loop Enhancement
    REQUIREMENTS_REVIEW = "requirements_review"
    PHENOTYPE_REVIEW = "phenotype_review"
    EXTRACTION_APPROVAL = "extraction_approval"
    QA_REVIEW = "qa_review"
    SCOPE_CHANGE = "scope_change"

    FEASIBILITY_VALIDATION = "feasibility_validation"
    FEASIBLE = "feasible"
    NOT_FEASIBLE = "not_feasible"
    SCHEDULE_KICKOFF = "schedule_kickoff"
    KICKOFF_COMPLETE = "kickoff_complete"
    DATA_EXTRACTION = "data_extraction"
    EXTRACTION_COMPLETE = "extraction_complete"
    QA_VALIDATION = "qa_validation"
    QA_PASSED = "qa_passed"
    QA_FAILED = "qa_failed"
    DATA_DELIVERY = "data_delivery"
    DELIVERED = "delivered"
    COMPLETE = "complete"
    FAILED = "failed"
    HUMAN_REVIEW = "human_review"


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
            # Requirements gathering complete -> Requirements Review (NEW APPROVAL GATE)
            ('requirements_agent', 'gather_requirements'): {
                'condition': lambda r: r.get('requirements_complete') == True,
                'next_agent': None,  # Waits for human approval
                'next_task': None,
                'next_state': WorkflowState.REQUIREMENTS_REVIEW
            },

            # Requirements approved -> Phenotype validation
            ('approval_service', 'approve_requirements'): {
                'condition': lambda r: r.get('approved') == True,
                'next_agent': 'phenotype_agent',
                'next_task': 'validate_feasibility',
                'next_state': WorkflowState.FEASIBILITY_VALIDATION
            },

            # Requirements rejected -> Back to requirements gathering
            ('approval_service', 'reject_requirements'): {
                'condition': lambda r: r.get('approved') == False,
                'next_agent': 'requirements_agent',
                'next_task': 'gather_requirements',
                'next_state': WorkflowState.REQUIREMENTS_GATHERING
            },

            # Feasibility validation complete -> Phenotype Review (NEW APPROVAL GATE)
            ('phenotype_agent', 'validate_feasibility'): {
                'condition': lambda r: r.get('feasible') == True,
                'next_agent': None,  # Waits for SQL approval
                'next_task': None,
                'next_state': WorkflowState.PHENOTYPE_REVIEW
            },

            # Phenotype SQL approved -> Schedule kickoff
            ('approval_service', 'approve_phenotype_sql'): {
                'condition': lambda r: r.get('approved') == True,
                'next_agent': 'calendar_agent',
                'next_task': 'schedule_kickoff_meeting',
                'next_state': WorkflowState.SCHEDULE_KICKOFF
            },

            # Phenotype SQL rejected -> Back to phenotype agent
            ('approval_service', 'reject_phenotype_sql'): {
                'condition': lambda r: r.get('approved') == False,
                'next_agent': 'phenotype_agent',
                'next_task': 'validate_feasibility',
                'next_state': WorkflowState.FEASIBILITY_VALIDATION
            },

            # Feasibility failed -> Human review
            ('phenotype_agent', 'validate_feasibility_failed'): {
                'condition': lambda r: r.get('feasible') == False,
                'next_agent': None,
                'next_task': None,
                'next_state': WorkflowState.NOT_FEASIBLE
            },

            # Kickoff meeting scheduled -> Extraction Approval (NEW APPROVAL GATE)
            ('calendar_agent', 'schedule_kickoff_meeting'): {
                'condition': lambda r: r.get('meeting_scheduled') == True,
                'next_agent': None,  # Waits for extraction approval
                'next_task': None,
                'next_state': WorkflowState.EXTRACTION_APPROVAL
            },

            # Extraction approved -> Data extraction
            ('approval_service', 'approve_extraction'): {
                'condition': lambda r: r.get('approved') == True,
                'next_agent': 'extraction_agent',
                'next_task': 'extract_data',
                'next_state': WorkflowState.DATA_EXTRACTION
            },

            # Extraction rejected -> Human review
            ('approval_service', 'reject_extraction'): {
                'condition': lambda r: r.get('approved') == False,
                'next_agent': None,
                'next_task': None,
                'next_state': WorkflowState.HUMAN_REVIEW
            },

            # Data extraction complete -> QA validation
            ('extraction_agent', 'extract_data'): {
                'condition': lambda r: r.get('extraction_complete') == True,
                'next_agent': 'qa_agent',
                'next_task': 'validate_extracted_data',
                'next_state': WorkflowState.QA_VALIDATION
            },

            # QA passed -> QA Review (NEW APPROVAL GATE)
            ('qa_agent', 'validate_extracted_data'): {
                'condition': lambda r: r.get('overall_status') == 'passed',
                'next_agent': None,  # Waits for QA approval
                'next_task': None,
                'next_state': WorkflowState.QA_REVIEW
            },

            # QA approved -> Data delivery
            ('approval_service', 'approve_qa'): {
                'condition': lambda r: r.get('approved') == True,
                'next_agent': 'delivery_agent',
                'next_task': 'deliver_data',
                'next_state': WorkflowState.DATA_DELIVERY
            },

            # QA rejected -> Back to extraction
            ('approval_service', 'reject_qa'): {
                'condition': lambda r: r.get('approved') == False,
                'next_agent': 'extraction_agent',
                'next_task': 'extract_data',
                'next_state': WorkflowState.DATA_EXTRACTION
            },

            # QA failed -> Human review
            ('qa_agent', 'validate_extracted_data_failed'): {
                'condition': lambda r: r.get('overall_status') == 'failed',
                'next_agent': None,
                'next_task': None,
                'next_state': WorkflowState.QA_FAILED
            },

            # Data delivered -> Complete
            ('delivery_agent', 'deliver_data'): {
                'condition': lambda r: r.get('delivered') == True,
                'next_agent': None,
                'next_task': None,
                'next_state': WorkflowState.COMPLETE
            },

            # Scope change workflows - can be triggered from any state
            ('coordinator_agent', 'handle_scope_change'): {
                'condition': lambda r: r.get('scope_approved') == True,
                'next_agent': 'requirements_agent',
                'next_task': 'gather_requirements',
                'next_state': WorkflowState.REQUIREMENTS_GATHERING
            },

            ('coordinator_agent', 'reject_scope_change'): {
                'condition': lambda r: r.get('scope_approved') == False,
                'next_agent': None,
                'next_task': None,
                'next_state': WorkflowState.HUMAN_REVIEW
            },
        }

    def determine_next_step(
        self,
        completed_agent: str,
        completed_task: str,
        result: Dict[str, Any]
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

        # Check condition
        if rule['condition'](result):
            next_step = {
                'next_agent': rule['next_agent'],
                'next_task': rule['next_task'],
                'next_state': rule['next_state']
            }
            logger.info(f"Workflow transition: {completed_agent}.{completed_task} -> {next_step['next_agent']}.{next_step['next_task']}")
            return next_step

        logger.info(f"Workflow condition not met for {rule_key}")
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
            WorkflowState.QA_FAILED
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
            WorkflowState.QA_REVIEW,
            WorkflowState.SCOPE_CHANGE,
            WorkflowState.HUMAN_REVIEW
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
            WorkflowState.QA_REVIEW: "qa",
            WorkflowState.SCOPE_CHANGE: "scope_change"
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
            "qa": 24,
            "scope_change": 48
        }
        return timeout_config.get(approval_type, 24)  # Default 24 hours

    def get_state_description(self, state: WorkflowState) -> str:
        """Get human-readable description of workflow state"""
        descriptions = {
            WorkflowState.NEW_REQUEST: "New request received",
            WorkflowState.REQUIREMENTS_GATHERING: "Gathering requirements from researcher",
            WorkflowState.REQUIREMENTS_COMPLETE: "Requirements complete, validating feasibility",

            # New approval state descriptions
            WorkflowState.REQUIREMENTS_REVIEW: "Waiting for informatician to review requirements",
            WorkflowState.PHENOTYPE_REVIEW: "Waiting for informatician to approve SQL query",
            WorkflowState.EXTRACTION_APPROVAL: "Waiting for approval to extract data",
            WorkflowState.QA_REVIEW: "Waiting for informatician to approve QA results",
            WorkflowState.SCOPE_CHANGE: "Scope change requested, waiting for review",

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
            WorkflowState.HUMAN_REVIEW: "Escalated to human review"
        }
        return descriptions.get(state, state.value)
