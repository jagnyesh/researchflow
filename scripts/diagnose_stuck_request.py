"""
Diagnostic script to analyze stuck request: REQ-20251105-A1E4902C

This script examines:
1. Research request state and current agent
2. All approvals (pending/approved/rejected)
3. Agent execution logs
4. State history
5. Workflow timeline
"""

import asyncio
import sys
import os
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import get_db_session
from app.database.models import (
    ResearchRequest,
    Approval,
    AgentExecution,
    RequirementsData,
    FeasibilityReport,
    DataDelivery,
    AuditLog,
)


async def diagnose_request(request_id: str):
    """Diagnose stuck request by examining all related database records"""
    print(f"\n{'='*80}")
    print(f"DIAGNOSTIC REPORT FOR REQUEST: {request_id}")
    print(f"{'='*80}\n")

    async with get_db_session() as session:
        # 1. Get research request
        print("[1] RESEARCH REQUEST STATE")
        print("-" * 80)
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        if not request:
            print(f"❌ Request {request_id} not found in database!")
            return

        print(f"Request ID: {request.id}")
        print(f"Created At: {request.created_at}")
        print(f"Updated At: {request.updated_at}")
        print(f"Completed At: {request.completed_at}")
        print(f"Current State: {request.current_state}")
        print(f"Current Agent: {request.current_agent}")
        print(f"Final State: {request.final_state}")
        print(f"Error Message: {request.error_message}")
        print(f"Researcher: {request.researcher_name} ({request.researcher_email})")
        print(f"IRB Number: {request.irb_number}")
        print()

        # 2. State history
        print("[2] STATE HISTORY")
        print("-" * 80)
        if request.state_history:
            for idx, entry in enumerate(request.state_history):
                timestamp = entry.get("timestamp", "N/A")
                state = entry.get("state", "N/A")
                approval_id = entry.get("approval_id", "")
                approved_by = entry.get("approved_by", "")
                notes = entry.get("notes", "")

                print(f"{idx + 1}. [{timestamp}] State: {state}")
                if approval_id:
                    print(f"   Approval ID: {approval_id}")
                if approved_by:
                    print(f"   Approved By: {approved_by}")
                if notes:
                    print(f"   Notes: {notes}")
        else:
            print("No state history found")
        print()

        # 3. Agents involved
        print("[3] WORKFLOW TIMELINE (Agents Involved)")
        print("-" * 80)
        if request.agents_involved:
            for idx, entry in enumerate(request.agents_involved):
                timestamp = entry.get("timestamp", "N/A")
                agent = entry.get("agent", "N/A")
                task = entry.get("task", "N/A")
                from_agent = entry.get("from_agent", "N/A")
                print(f"{idx + 1}. [{timestamp}] {agent} <- {from_agent}")
                print(f"   Task: {task}")
        else:
            print("No agents involved yet")
        print()

        # 4. All approvals
        print("[4] APPROVALS")
        print("-" * 80)
        result = await session.execute(
            select(Approval)
            .where(Approval.request_id == request_id)
            .order_by(Approval.submitted_at.asc())
        )
        approvals = result.scalars().all()

        if approvals:
            for approval in approvals:
                status_icon = {
                    "pending": "⏳",
                    "approved": "✅",
                    "rejected": "❌",
                    "modified": "✏️",
                    "timeout": "⏰",
                }.get(approval.status, "❓")

                print(f"{status_icon} {approval.approval_type.upper()} (ID: {approval.id})")
                print(f"   Status: {approval.status}")
                print(f"   Submitted At: {approval.submitted_at}")
                print(f"   Submitted By: {approval.submitted_by}")
                print(f"   Reviewed At: {approval.reviewed_at}")
                print(f"   Reviewed By: {approval.reviewed_by}")
                print(f"   Timeout At: {approval.timeout_at}")
                print(f"   Timed Out: {approval.timed_out}")
                print(f"   Escalated: {approval.escalated}")

                if approval.review_notes:
                    print(f"   Review Notes: {approval.review_notes}")

                # Show approval data keys
                if approval.approval_data:
                    print(f"   Approval Data Keys: {list(approval.approval_data.keys())}")
                print()
        else:
            print("No approvals found")
        print()

        # 5. Agent execution logs
        print("[5] AGENT EXECUTION LOGS")
        print("-" * 80)
        result = await session.execute(
            select(AgentExecution)
            .where(AgentExecution.request_id == request_id)
            .order_by(AgentExecution.started_at.asc())
        )
        executions = result.scalars().all()

        if executions:
            for execution in executions:
                status_icon = {"success": "✅", "failed": "❌", "retrying": "🔄"}.get(
                    execution.status, "❓"
                )

                print(f"{status_icon} {execution.agent_id}.{execution.task}")
                print(f"   Status: {execution.status}")
                print(f"   Started At: {execution.started_at}")
                print(f"   Completed At: {execution.completed_at}")
                print(
                    f"   Duration: {execution.duration_seconds:.2f}s"
                    if execution.duration_seconds
                    else "   Duration: N/A"
                )
                print(f"   Retry Count: {execution.retry_count}")

                if execution.error:
                    print(f"   Error: {execution.error}")

                # Show result keys
                if execution.result:
                    print(f"   Result Keys: {list(execution.result.keys())}")
                print()
        else:
            print("No agent executions found")
        print()

        # 6. Requirements data
        print("[6] REQUIREMENTS DATA")
        print("-" * 80)
        result = await session.execute(
            select(RequirementsData).where(RequirementsData.request_id == request_id)
        )
        requirements = result.scalar_one_or_none()

        if requirements:
            print(f"Study Title: {requirements.study_title}")
            print(f"Principal Investigator: {requirements.principal_investigator}")
            print(f"IRB Number: {requirements.irb_number}")
            print(f"Completeness Score: {requirements.completeness_score:.2f}")
            print(f"Is Complete: {requirements.is_complete}")
            print(f"PHI Level: {requirements.phi_level}")
            print(f"Delivery Format: {requirements.delivery_format}")
            print(f"Data Elements: {requirements.data_elements}")
            print(f"Inclusion Criteria: {len(requirements.inclusion_criteria)} items")
            print(f"Exclusion Criteria: {len(requirements.exclusion_criteria)} items")
        else:
            print("No requirements data found")
        print()

        # 7. Feasibility report
        print("[7] FEASIBILITY REPORT")
        print("-" * 80)
        result = await session.execute(
            select(FeasibilityReport).where(FeasibilityReport.request_id == request_id)
        )
        feasibility = result.scalar_one_or_none()

        if feasibility:
            print(f"Is Feasible: {feasibility.is_feasible}")
            print(f"Feasibility Score: {feasibility.feasibility_score:.2f}")
            print(f"Estimated Cohort Size: {feasibility.estimated_cohort_size}")
            print(f"Estimated Extraction Time: {feasibility.estimated_extraction_time_hours}h")
            print(
                f"SQL Length: {len(feasibility.phenotype_sql)} chars"
                if feasibility.phenotype_sql
                else "No SQL"
            )
        else:
            print("No feasibility report found")
        print()

        # 8. Data delivery
        print("[8] DATA DELIVERY")
        print("-" * 80)
        result = await session.execute(
            select(DataDelivery).where(DataDelivery.request_id == request_id)
        )
        delivery = result.scalar_one_or_none()

        if delivery:
            print(f"Delivery Location: {delivery.delivery_location}")
            print(f"Delivery Format: {delivery.delivery_format}")
            print(f"Cohort Size: {delivery.cohort_size}")
            print(f"Has Preview Data: {bool(delivery.preview_data)}")
            print(f"Has Preview QA Report: {bool(delivery.preview_qa_report)}")
            print(f"Has QA Report: {bool(delivery.qa_report)}")
            print(f"Notification Sent: {delivery.notification_sent}")
        else:
            print("No data delivery found")
        print()

        # 9. Audit log (last 20 entries)
        print("[9] AUDIT LOG (Last 20 Entries)")
        print("-" * 80)
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.request_id == request_id)
            .order_by(AuditLog.timestamp.desc())
            .limit(20)
        )
        audit_logs = result.scalars().all()

        if audit_logs:
            for log in reversed(audit_logs):  # Show chronologically
                severity_icon = {
                    "debug": "🔍",
                    "info": "ℹ️",
                    "warning": "⚠️",
                    "error": "❌",
                    "critical": "🔥",
                }.get(log.severity, "❓")

                print(f"{severity_icon} [{log.timestamp}] {log.event_type}")
                print(f"   Agent: {log.agent_id}")
                print(f"   Triggered By: {log.triggered_by}")
                if log.event_data:
                    print(f"   Event Data: {log.event_data}")
                print()
        else:
            print("No audit logs found")
        print()

        # 10. Diagnosis summary
        print("[10] DIAGNOSIS SUMMARY")
        print("=" * 80)

        # Check for common stuck patterns
        issues = []

        # Check 1: State vs Agent mismatch
        if request.current_state == "human_review" and request.current_agent:
            issues.append(
                f"⚠️  STATE MISMATCH: State is 'human_review' but current_agent is '{request.current_agent}'"
            )
            issues.append(
                "   This indicates the request was sent to human review but the agent field was not cleared"
            )

        # Check 2: Pending approvals
        pending_approvals = [a for a in approvals if a.status == "pending"]
        if pending_approvals:
            for approval in pending_approvals:
                issues.append(f"⏳ PENDING APPROVAL: {approval.approval_type} (ID: {approval.id})")
                issues.append(f"   Submitted at: {approval.submitted_at}")

        # Check 3: No recent agent activity
        if executions:
            last_execution = executions[-1]
            if last_execution.completed_at:
                time_since_last = datetime.now() - last_execution.completed_at
                if time_since_last.total_seconds() > 300:  # 5 minutes
                    issues.append(
                        f"⏰ NO RECENT ACTIVITY: Last agent execution was {time_since_last.total_seconds()/60:.1f} minutes ago"
                    )

        # Check 4: Failed executions
        failed_executions = [e for e in executions if e.status == "failed"]
        if failed_executions:
            issues.append(f"❌ FAILED EXECUTIONS: {len(failed_executions)} agent executions failed")
            for execution in failed_executions:
                issues.append(f"   - {execution.agent_id}.{execution.task}: {execution.error}")

        # Check 5: Approved approvals not triggering next step
        approved_approvals = [a for a in approvals if a.status in ["approved", "modified"]]
        if approved_approvals:
            for approval in approved_approvals:
                # Check if there's a subsequent agent execution after this approval
                approval_time = approval.reviewed_at or approval.submitted_at
                executions_after = [e for e in executions if e.started_at > approval_time]

                if not executions_after:
                    issues.append(
                        f"🚫 APPROVAL NOT PROCESSED: {approval.approval_type} (ID: {approval.id}) was approved but no subsequent agent execution found"
                    )
                    issues.append(f"   Approved at: {approval.reviewed_at}")
                    issues.append(
                        f"   This suggests orchestrator did not route to next agent after approval"
                    )

        if issues:
            print("ISSUES FOUND:")
            for issue in issues:
                print(issue)
        else:
            print("✅ No obvious issues detected")

        print()


async def main():
    request_id = "REQ-20251105-A1E4902C"
    await diagnose_request(request_id)


if __name__ == "__main__":
    asyncio.run(main())
