#!/usr/bin/env python3
"""
Manually advance workflow for stuck requests after SQL approval.

This script checks for requests stuck in phenotype_review with approved SQL,
and advances them to the next state (preview_extraction).
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import get_db_session
from app.database.models import ResearchRequest
from app.orchestrator.workflow_engine import WorkflowEngine
from sqlalchemy import select


async def advance_stuck_request(request_id: str):
    """Manually advance a stuck request to the next workflow state"""

    async with get_db_session() as session:
        # Get the request
        result = await session.execute(
            select(ResearchRequest).where(ResearchRequest.id == request_id)
        )
        request = result.scalar_one_or_none()

        if not request:
            print(f"❌ Request {request_id} not found")
            return

        print(f"📋 Current state: {request.current_state}")
        print(f"📋 Current agent: {request.current_agent}")

        # Initialize workflow engine
        workflow_engine = WorkflowEngine()

        # Get the next transition
        context = {
            "request_id": request_id,
            "sql_approved": True,
            "preview_enabled": True,  # Enable preview extraction
        }

        # Trigger transition from phenotype_review → preview_extraction
        next_state = workflow_engine.transition(
            current_state=request.current_state, context=context
        )

        print(f"\n✅ Next state: {next_state}")

        # Update the request state
        request.current_state = next_state
        request.current_agent = "extraction_agent"

        await session.commit()

        print(f"✅ Request {request_id} advanced to {next_state}")
        print(f"✅ Current agent: extraction_agent")

        return next_state


async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Manually advance stuck workflow")
    parser.add_argument("request_id", help="Request ID to advance")

    args = parser.parse_args()

    print("=" * 60)
    print("MANUALLY ADVANCE WORKFLOW")
    print("=" * 60 + "\n")

    await advance_stuck_request(args.request_id)


if __name__ == "__main__":
    asyncio.run(main())
