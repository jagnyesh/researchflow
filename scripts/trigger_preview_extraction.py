#!/usr/bin/env python3
"""
Manually trigger preview extraction for a request that has SQL approval
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db_session
from app.database.models import Approval
from sqlalchemy import select


async def trigger_preview_extraction(request_id: str):
    """Trigger preview extraction for a request with SQL approval"""
    async with get_db_session() as session:
        # Get the phenotype_sql approval
        result = await session.execute(
            select(Approval)
            .where(Approval.request_id == request_id)
            .where(Approval.approval_type == "phenotype_sql")
            .where(Approval.status == "approved")
        )
        approval = result.scalar_one_or_none()

        if not approval:
            print(f"❌ No approved SQL found for {request_id}")
            return

        print(f"✅ Found SQL approval {approval.id} for {request_id}")
        print(f"   Approval data keys: {list(approval.approval_data.keys())}")

        # Import orchestrator and trigger workflow continuation
        from app.orchestrator.orchestrator import Orchestrator

        orchestrator = Orchestrator()

        # Initialize agents (needed for routing)
        from app.agents.extraction_agent import ExtractionAgent
        from app.agents.qa_agent import QAAgent

        hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")

        # Convert to asyncpg format
        if "postgresql://" in hapi_db_url and "+asyncpg" not in hapi_db_url:
            hapi_db_url = hapi_db_url.replace("postgresql://", "postgresql+asyncpg://")

        orchestrator.register_agent("extraction_agent", ExtractionAgent(database_url=hapi_db_url))
        orchestrator.register_agent("qa_agent", QAAgent())

        # Manually continue workflow after approval
        print(f"🚀 Triggering preview extraction...")
        await orchestrator._continue_workflow_after_approval(approval.id, "approve", None)

        print(f"✅ Preview extraction triggered successfully!")


if __name__ == "__main__":
    request_id = "REQ-20251104-CF18C297"
    if len(sys.argv) > 1:
        request_id = sys.argv[1]

    asyncio.run(trigger_preview_extraction(request_id))
