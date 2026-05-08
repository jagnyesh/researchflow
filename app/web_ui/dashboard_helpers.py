"""
Dashboard Helper Functions

Provides database query functions for admin dashboard and testing.
Extracted from admin_dashboard.py to enable unit testing.
"""

from datetime import datetime, timedelta
from sqlalchemy import select, func
from typing import List, Dict, Any

from ..database import get_db_session
from ..database.models import (
    ResearchRequest,
    AgentExecution,
    Escalation,
    Approval,
)
from ..orchestrator.workflow_engine import WorkflowState


# Agent IDs used across the system
AGENT_IDS = [
    "requirements_agent",
    "phenotype_agent",
    "calendar_agent",
    "extraction_agent",
    "qa_agent",
    "delivery_agent",
]


async def get_agent_metrics_from_db() -> List[Dict[str, Any]]:
    """
    Query database for agent execution metrics.

    Returns:
        List of metrics per agent with execution counts and success rates
    """
    async with get_db_session() as session:
        metrics = []

        for agent_id in AGENT_IDS:
            # Count total executions
            total_query = select(func.count(AgentExecution.id)).where(
                AgentExecution.agent_id == agent_id
            )
            total_result = await session.execute(total_query)
            total = total_result.scalar() or 0

            # Count successful executions
            success_query = select(func.count(AgentExecution.id)).where(
                AgentExecution.agent_id == agent_id, AgentExecution.status == "completed"
            )
            success_result = await session.execute(success_query)
            successful = success_result.scalar() or 0

            # Count failed executions
            failed_query = select(func.count(AgentExecution.id)).where(
                AgentExecution.agent_id == agent_id, AgentExecution.status == "failed"
            )
            failed_result = await session.execute(failed_query)
            failed = failed_result.scalar() or 0

            # Calculate success rate
            success_rate = (successful / total * 100) if total > 0 else 0

            metrics.append(
                {
                    "agent_id": agent_id,
                    "total_executions": total,
                    "successful": successful,
                    "failed": failed,
                    "success_rate": round(success_rate, 1),
                }
            )

        return metrics


async def get_all_requests_from_db() -> List[Dict[str, Any]]:
    """
    Query database for all research requests.

    Returns:
        List of research requests with status and metadata
    """
    async with get_db_session() as session:
        query = select(ResearchRequest).order_by(ResearchRequest.created_at.desc())
        result = await session.execute(query)
        requests = result.scalars().all()

        return [
            {
                "id": req.id,
                "title": (
                    req.initial_request[:100] if req.initial_request else "Untitled"
                ),  # Use first 100 chars of request
                "status": req.current_state,
                "workflow_state": req.current_state,
                "created_at": req.created_at,
                "updated_at": req.updated_at,
                "researcher_email": req.researcher_email,
            }
            for req in requests
        ]


async def get_escalations_from_db() -> List[Dict[str, Any]]:
    """
    Query database for escalations requiring human review.

    Returns:
        List of escalations with details
    """
    async with get_db_session() as session:
        query = (
            select(Escalation)
            .where(Escalation.status == "open")
            .order_by(Escalation.created_at.desc())
        )
        result = await session.execute(query)
        escalations = result.scalars().all()

        return [
            {
                "id": esc.id,
                "request_id": esc.request_id,
                "agent_id": esc.agent_id,
                "severity": esc.severity,
                "reason": esc.reason,
                "context": esc.context,
                "created_at": esc.created_at,
                "status": esc.status,
            }
            for esc in escalations
        ]


async def get_analytics_from_db() -> Dict[str, Any]:
    """
    Query database for system analytics and KPIs.

    Returns:
        Dictionary with system-wide metrics
    """
    async with get_db_session() as session:
        # Total requests
        total_requests_query = select(func.count(ResearchRequest.id))
        total_requests_result = await session.execute(total_requests_query)
        total_requests = total_requests_result.scalar() or 0

        # Requests by status (using current_state field)
        completed_query = select(func.count(ResearchRequest.id)).where(
            ResearchRequest.current_state == WorkflowState.COMPLETE
        )
        completed_result = await session.execute(completed_query)
        completed = completed_result.scalar() or 0

        in_progress_query = select(func.count(ResearchRequest.id)).where(
            ResearchRequest.current_state.in_(
                [
                    WorkflowState.REQUIREMENTS_GATHERING,
                    WorkflowState.FEASIBILITY_VALIDATION,
                    WorkflowState.DATA_EXTRACTION,
                    WorkflowState.QA_VALIDATION,
                ]
            )
        )
        in_progress_result = await session.execute(in_progress_query)
        in_progress = in_progress_result.scalar() or 0

        # Agent executions
        total_executions_query = select(func.count(AgentExecution.id))
        total_executions_result = await session.execute(total_executions_query)
        total_executions = total_executions_result.scalar() or 0

        # Open escalations
        open_escalations_query = select(func.count(Escalation.id)).where(
            Escalation.status == "open"
        )
        open_escalations_result = await session.execute(open_escalations_query)
        open_escalations = open_escalations_result.scalar() or 0

        return {
            "total_requests": total_requests,
            "completed_requests": completed,
            "in_progress_requests": in_progress,
            "total_agent_executions": total_executions,
            "open_escalations": open_escalations,
            "completion_rate": round(
                (completed / total_requests * 100) if total_requests > 0 else 0, 1
            ),
        }
