"""
Coordinator Agent for ResearchFlow

Handles proactive workflow coordination, scope changes, and stakeholder management.
Fills the gap identified in real-world clinical research workflows where admin staff
coordinate emails, scope changes, and stakeholder communication.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class CoordinatorAgent(BaseAgent):
    """
    Proactive workflow coordination and stakeholder management

    Responsibilities:
    - Manage scope changes (Gap #2 from roadmap)
    - Coordinate stakeholder communication
    - Send email updates at key milestones
    - Handle timeline negotiations
    - Escalate proactively based on thresholds
    - Coordinate approval workflows
    """

    def __init__(self, orchestrator=None):
        super().__init__(agent_id="coordinator_agent", orchestrator=orchestrator)
        self.email_templates = self._load_email_templates()

    def _load_email_templates(self) -> Dict[str, str]:
        """Load email templates for different events"""
        return {
            "requirements_complete": """
Subject: Requirements Review Needed - {request_id}

Dear Informatician,

A new research data request has been submitted and requirements have been extracted.

Request ID: {request_id}
Researcher: {researcher_name}
Department: {researcher_department}

Please review the extracted requirements in the Admin Dashboard:
{dashboard_url}/approvals/{approval_id}

The requirements will be reviewed for medical accuracy before proceeding to phenotype generation.

Best regards,
ResearchFlow System
            """,

            "phenotype_sql_review": """
Subject: SQL Query Review Needed - {request_id}

Dear Informatician,

A phenotype SQL query has been generated and requires your review before execution.

Request ID: {request_id}
Researcher: {researcher_name}
Estimated Cohort: {estimated_cohort}

Please review and approve the SQL query in the Admin Dashboard:
{dashboard_url}/approvals/{approval_id}

IMPORTANT: This SQL will execute against the production FHIR database once approved.

Best regards,
ResearchFlow System
            """,

            "extraction_notice": """
Subject: Data Extraction Approved - {request_id}

Dear {researcher_name},

Your data extraction request has been approved and will begin shortly.

Request ID: {request_id}
Estimated Cohort Size: {cohort_size}
Data Elements: {data_elements}

You will receive another notification once extraction is complete and QA validation passes.

Best regards,
ResearchFlow System
            """,

            "qa_complete": """
Subject: QA Complete - Data Ready for Review - {request_id}

Dear {researcher_name},

Quality assurance has been completed for your data request.

Request ID: {request_id}
QA Status: {qa_status}
Final Cohort Size: {cohort_size}

{qa_summary}

Please review the QA report and approve for delivery:
{dashboard_url}/requests/{request_id}

Best regards,
ResearchFlow System
            """,

            "scope_change_notification": """
Subject: Scope Change Request - {request_id}

Dear Team,

A scope change has been requested for an active research data request.

Request ID: {request_id}
Requested by: {researcher_name}
Current State: {current_state}

Original Requirements:
{original_requirements}

Requested Changes:
{requested_changes}

Impact Analysis:
{impact_analysis}

Please review and approve/reject in the Admin Dashboard:
{dashboard_url}/approvals/{approval_id}

Best regards,
ResearchFlow System
            """
        }

    async def execute_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute coordination task"""
        task_map = {
            "send_requirements_complete_email": self._send_requirements_complete_email,
            "send_sql_review_email": self._send_sql_review_email,
            "send_extraction_notice": self._send_extraction_notice,
            "send_qa_complete_email": self._send_qa_complete_email,
            "handle_scope_change": self._handle_scope_change,
            "send_scope_change_notification": self._send_scope_change_notification,
            "coordinate_approval": self._coordinate_approval,
            "handle_timeline_negotiation": self._handle_timeline_negotiation,
            "send_stakeholder_update": self._send_stakeholder_update,
        }

        handler = task_map.get(task)
        if not handler:
            raise ValueError(f"Unknown task: {task}")

        return await handler(context)

    async def _send_requirements_complete_email(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Send email notification when requirements extraction is complete"""
        request_id = context.get("request_id")
        researcher_name = context.get("researcher_name", "Unknown")
        researcher_department = context.get("researcher_department", "Unknown")
        approval_id = context.get("approval_id")

        email_body = self.email_templates["requirements_complete"].format(
            request_id=request_id,
            researcher_name=researcher_name,
            researcher_department=researcher_department,
            dashboard_url="http://localhost:8502",  # TODO: Get from config
            approval_id=approval_id
        )

        # TODO: Integrate with actual email service (MCP email server)
        logger.info(f"[{self.agent_id}] Sending requirements complete email for {request_id}")
        logger.debug(f"Email body: {email_body}")

        return {
            "email_sent": True,
            "email_type": "requirements_complete",
            "recipient": "informatician@example.com"  # TODO: Get from config
        }

    async def _send_sql_review_email(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Send email requesting SQL review"""
        request_id = context.get("request_id")
        researcher_name = context.get("researcher_name", "Unknown")
        estimated_cohort = context.get("estimated_cohort", "Unknown")
        approval_id = context.get("approval_id")

        email_body = self.email_templates["phenotype_sql_review"].format(
            request_id=request_id,
            researcher_name=researcher_name,
            estimated_cohort=estimated_cohort,
            dashboard_url="http://localhost:8502",
            approval_id=approval_id
        )

        logger.info(f"[{self.agent_id}] Sending SQL review email for {request_id}")
        logger.debug(f"Email body: {email_body}")

        return {
            "email_sent": True,
            "email_type": "phenotype_sql_review",
            "recipient": "informatician@example.com"
        }

    async def _send_extraction_notice(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Send extraction approval notice to researcher"""
        request_id = context.get("request_id")
        researcher_name = context.get("researcher_name", "Unknown")
        researcher_email = context.get("researcher_email", "researcher@example.com")
        cohort_size = context.get("cohort_size", "Unknown")
        data_elements = context.get("data_elements", [])

        email_body = self.email_templates["extraction_notice"].format(
            request_id=request_id,
            researcher_name=researcher_name,
            cohort_size=cohort_size,
            data_elements=", ".join(data_elements) if data_elements else "N/A"
        )

        logger.info(f"[{self.agent_id}] Sending extraction notice to {researcher_email}")
        logger.debug(f"Email body: {email_body}")

        return {
            "email_sent": True,
            "email_type": "extraction_notice",
            "recipient": researcher_email
        }

    async def _send_qa_complete_email(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Send QA completion notice to researcher"""
        request_id = context.get("request_id")
        researcher_name = context.get("researcher_name", "Unknown")
        researcher_email = context.get("researcher_email", "researcher@example.com")
        qa_status = context.get("qa_status", "Unknown")
        cohort_size = context.get("cohort_size", "Unknown")
        qa_summary = context.get("qa_summary", "No summary available")

        email_body = self.email_templates["qa_complete"].format(
            request_id=request_id,
            researcher_name=researcher_name,
            qa_status=qa_status,
            cohort_size=cohort_size,
            qa_summary=qa_summary,
            dashboard_url="http://localhost:8501"  # Researcher portal
        )

        logger.info(f"[{self.agent_id}] Sending QA complete email to {researcher_email}")
        logger.debug(f"Email body: {email_body}")

        return {
            "email_sent": True,
            "email_type": "qa_complete",
            "recipient": researcher_email
        }

    async def _handle_scope_change(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle researcher-initiated scope changes

        Analyzes impact and routes for approval
        """
        request_id = context.get("request_id")
        current_state = context.get("current_state")
        requested_changes = context.get("requested_changes", {})
        original_requirements = context.get("original_requirements", {})

        logger.info(f"[{self.agent_id}] Handling scope change for {request_id}")

        # Analyze impact
        impact_analysis = await self._analyze_scope_change_impact(
            original_requirements,
            requested_changes,
            current_state
        )

        logger.info(f"[{self.agent_id}] Scope change impact: {impact_analysis['severity']}")

        # Create approval request for scope change
        # This will be handled by the approval service

        return {
            "scope_change_analyzed": True,
            "impact_analysis": impact_analysis,
            "requires_approval": True,
            "next_agent": None,  # Waits for approval
            "next_task": None,
            "additional_context": {
                "scope_change_impact": impact_analysis
            }
        }

    async def _analyze_scope_change_impact(
        self,
        original_requirements: Dict[str, Any],
        requested_changes: Dict[str, Any],
        current_state: str
    ) -> Dict[str, Any]:
        """
        Analyze impact of scope changes

        Returns:
            Impact analysis with severity and recommended actions
        """
        impact = {
            "severity": "medium",
            "requires_rework": False,
            "restart_from_state": None,
            "estimated_delay_hours": 0,
            "affected_components": []
        }

        # Check if inclusion/exclusion criteria changed
        if "inclusion_criteria" in requested_changes or "exclusion_criteria" in requested_changes:
            impact["severity"] = "high"
            impact["requires_rework"] = True
            impact["restart_from_state"] = "requirements_gathering"
            impact["estimated_delay_hours"] = 24
            impact["affected_components"].extend(["phenotype", "extraction", "qa"])

        # Check if data elements changed
        elif "data_elements" in requested_changes:
            impact["severity"] = "medium"
            impact["requires_rework"] = True
            impact["restart_from_state"] = "feasibility_validation"
            impact["estimated_delay_hours"] = 12
            impact["affected_components"].extend(["extraction", "qa"])

        # Check if time period changed
        elif "time_period_start" in requested_changes or "time_period_end" in requested_changes:
            impact["severity"] = "low"
            impact["requires_rework"] = True
            impact["restart_from_state"] = "feasibility_validation"
            impact["estimated_delay_hours"] = 6
            impact["affected_components"].append("phenotype")

        return impact

    async def _send_scope_change_notification(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Send scope change notification to all stakeholders"""
        request_id = context.get("request_id")
        researcher_name = context.get("researcher_name", "Unknown")
        current_state = context.get("current_state", "Unknown")
        original_requirements = context.get("original_requirements", {})
        requested_changes = context.get("requested_changes", {})
        impact_analysis = context.get("impact_analysis", {})
        approval_id = context.get("approval_id")

        email_body = self.email_templates["scope_change_notification"].format(
            request_id=request_id,
            researcher_name=researcher_name,
            current_state=current_state,
            original_requirements=str(original_requirements),
            requested_changes=str(requested_changes),
            impact_analysis=str(impact_analysis),
            dashboard_url="http://localhost:8502",
            approval_id=approval_id
        )

        # Send to informatician and admin
        recipients = ["informatician@example.com", "admin@example.com"]

        logger.info(f"[{self.agent_id}] Sending scope change notification to {len(recipients)} stakeholders")
        logger.debug(f"Email body: {email_body}")

        return {
            "email_sent": True,
            "email_type": "scope_change_notification",
            "recipients": recipients
        }

    async def _coordinate_approval(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Coordinate human approval workflow

        Sends notifications and tracks approval status
        """
        approval_type = context.get("approval_type")
        request_id = context.get("request_id")

        logger.info(f"[{self.agent_id}] Coordinating {approval_type} approval for {request_id}")

        # Send appropriate notification based on approval type
        email_task_map = {
            "requirements": "send_requirements_complete_email",
            "phenotype_sql": "send_sql_review_email",
            "extraction": "send_extraction_notice",
            "qa": "send_qa_complete_email",
            "scope_change": "send_scope_change_notification"
        }

        email_task = email_task_map.get(approval_type)
        if email_task:
            await self.execute_task(email_task, context)

        return {
            "approval_coordinated": True,
            "approval_type": approval_type,
            "notification_sent": True
        }

    async def _handle_timeline_negotiation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle timeline negotiations between researcher and informatician

        Future enhancement: Integrate with calendar systems
        """
        request_id = context.get("request_id")
        proposed_timeline = context.get("proposed_timeline", {})

        logger.info(f"[{self.agent_id}] Handling timeline negotiation for {request_id}")

        # For now, log the timeline proposal
        # Future: Integrate with calendar APIs to check availability

        return {
            "timeline_negotiated": True,
            "proposed_timeline": proposed_timeline,
            "status": "pending_confirmation"
        }

    async def _send_stakeholder_update(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send progress update to stakeholders

        Called at major workflow milestones
        """
        request_id = context.get("request_id")
        current_state = context.get("current_state", "Unknown")
        update_message = context.get("update_message", "Status update")

        logger.info(f"[{self.agent_id}] Sending stakeholder update for {request_id}: {current_state}")

        # TODO: Send to all stakeholders (researcher, informatician, admin)
        # For now, just log

        return {
            "update_sent": True,
            "current_state": current_state,
            "message": update_message
        }
