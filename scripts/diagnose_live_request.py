"""
Diagnose a live stuck request by request ID
"""

import asyncio
import sys
import os
from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import get_db_session
from app.database.models import ResearchRequest, Approval, AgentExecution, AuditLog
from datetime import datetime


async def diagnose(request_id: str):
    """Diagnose request"""
    print(f"\n{'='*80}")
    print(f"DIAGNOSING REQUEST: {request_id}")
    print(f"{'='*80}\n")

    async with get_db_session() as session:
        # Get request
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        if not request:
            print(f"❌ Request {request_id} not found!")
            return

        print(f"[CURRENT STATE]")
        print(f"  State: {request.current_state}")
        print(f"  Agent: {request.current_agent}")
        print(f"  Created: {request.created_at}")
        print(f"  Updated: {request.updated_at}")
        print(f"  Completed: {request.completed_at}")
        print()

        # Get approvals
        result = await session.execute(
            select(Approval)
            .where(Approval.request_id == request_id)
            .order_by(Approval.submitted_at.asc())
        )
        approvals = result.scalars().all()

        print(f"[APPROVALS] ({len(approvals)} total)")
        for approval in approvals:
            status_icon = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(
                approval.status, "❓"
            )
            print(f"  {status_icon} {approval.approval_type} (ID: {approval.id})")
            print(f"     Status: {approval.status}")
            print(f"     Submitted: {approval.submitted_at}")
            print(f"     Reviewed: {approval.reviewed_at}")
            print(f"     Reviewed By: {approval.reviewed_by}")
        print()

        # Get agent executions
        result = await session.execute(
            select(AgentExecution)
            .where(AgentExecution.request_id == request_id)
            .order_by(AgentExecution.started_at.asc())
        )
        executions = result.scalars().all()

        print(f"[AGENT EXECUTIONS] ({len(executions)} total)")
        for execution in executions:
            status_icon = {"success": "✅", "failed": "❌"}.get(execution.status, "❓")
            print(f"  {status_icon} {execution.agent_id}.{execution.task}")
            print(f"     Status: {execution.status}")
            print(f"     Started: {execution.started_at}")
            print(f"     Completed: {execution.completed_at}")
            if execution.error:
                print(f"     Error: {execution.error}")
        print()

        # Get recent audit logs
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.request_id == request_id)
            .order_by(AuditLog.timestamp.desc())
            .limit(20)
        )
        audit_logs = result.scalars().all()

        print(f"[AUDIT LOG] (Last 20 entries)")
        for log in reversed(audit_logs):
            severity_icon = {
                "debug": "🔍",
                "info": "ℹ️",
                "warning": "⚠️",
                "error": "❌",
                "critical": "🔥",
            }.get(log.severity, "❓")
            print(f"  {severity_icon} [{log.timestamp}] {log.event_type}")
            print(f"     Agent: {log.agent_id}")
            if log.event_data:
                print(f"     Data: {log.event_data}")
        print()

        # Diagnosis
        print(f"[DIAGNOSIS]")
        print(f"={'='*80}")

        # Check if phenotype_sql was approved
        phenotype_approvals = [
            a for a in approvals if a.approval_type == "phenotype_sql" and a.status == "approved"
        ]
        if phenotype_approvals:
            print(f"✅ Phenotype SQL was approved at {phenotype_approvals[0].reviewed_at}")

            # Check if extraction_agent.extract_preview was executed
            preview_executions = [
                e
                for e in executions
                if e.agent_id == "extraction_agent" and e.task == "extract_preview"
            ]
            if preview_executions:
                print(f"✅ extraction_agent.extract_preview was executed")
            else:
                print(
                    f"❌ extraction_agent.extract_preview was NOT executed after phenotype_sql approval"
                )
                print(f"   This indicates the orchestrator did not route to extraction_agent")
        else:
            print(f"⏳ Phenotype SQL approval is pending or not created yet")

        # Check if preview_qa was approved
        preview_qa_approvals = [
            a for a in approvals if a.approval_type == "preview_qa" and a.status == "approved"
        ]
        if preview_qa_approvals:
            print(f"✅ Preview QA was approved at {preview_qa_approvals[0].reviewed_at}")

            # Check if extraction_agent.extract_data was executed
            full_extractions = [
                e
                for e in executions
                if e.agent_id == "extraction_agent" and e.task == "extract_data"
            ]
            if full_extractions:
                print(f"✅ extraction_agent.extract_data was executed")
            else:
                print(
                    f"❌ extraction_agent.extract_data was NOT executed after preview_qa approval"
                )
                print(f"   This indicates the orchestrator did not route to extraction_agent")
        else:
            print(f"⏳ Preview QA approval is pending or not created yet")

        print()


async def main():
    request_id = input("Enter request ID (or press Enter for REQ-20251105-60CB5525): ").strip()
    if not request_id:
        request_id = "REQ-20251105-60CB5525"

    await diagnose(request_id)


if __name__ == "__main__":
    asyncio.run(main())
