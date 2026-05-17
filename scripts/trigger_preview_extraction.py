#!/usr/bin/env python3
"""
Manually trigger preview extraction for a request that has phenotype_sql approval.

Sprint 7.2: migrated from A2A's `Orchestrator._continue_workflow_after_approval`
(which was a private method that did not exist as named in production —
this script was already broken pre-migration). LangGraph's `process_approval_response`
is the production-supported path: it persists the approval status and resumes
the workflow from the checkpoint, which routes through preview_extraction.
"""
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.database import get_db_session
from app.database.models import Approval
from app.langchain_orchestrator.request_facade import LangGraphRequestFacade


async def trigger_preview_extraction(request_id: str):
    """Trigger preview extraction for a request with phenotype_sql approval."""
    async with get_db_session() as session:
        result = await session.execute(
            select(Approval)
            .where(Approval.request_id == request_id)
            .where(Approval.approval_type == "phenotype_sql")
            .where(Approval.status == "approved")
        )
        approval = result.scalar_one_or_none()

        if not approval:
            print(f"❌ No approved phenotype_sql found for {request_id}")
            return

        print(f"✅ Found phenotype_sql approval {approval.id} for {request_id}")
        approval_id = approval.id

    orchestrator = LangGraphRequestFacade(use_real_agents=True, use_persistence=True)
    print("🚀 Triggering preview extraction via process_approval_response...")
    await orchestrator.process_approval_response(
        approval_id=approval_id,
        reviewer="trigger_preview_extraction_script",
        decision="approve",
        notes="Manually triggered via scripts/trigger_preview_extraction.py",
    )
    print(
        "✅ Preview extraction triggered — LangGraph workflow resumed from phenotype_review checkpoint"
    )


if __name__ == "__main__":
    request_id = "REQ-20251104-CF18C297"
    if len(sys.argv) > 1:
        request_id = sys.argv[1]

    asyncio.run(trigger_preview_extraction(request_id))
