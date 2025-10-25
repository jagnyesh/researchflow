"""
Utility Script: Process Stuck Requests

This script finds and processes requests that are stuck in early workflow states
(new_request, requirements_gathering) and triggers the orchestrator to continue them.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import get_db_session, init_db
from app.database.models import ResearchRequest
from app.orchestrator.orchestrator import ResearchRequestOrchestrator
from app.agents import (
    RequirementsAgent,
    PhenotypeValidationAgent,
    CalendarAgent,
    DataExtractionAgent,
    QualityAssuranceAgent,
    DeliveryAgent
)
from app.agents.coordinator_agent import CoordinatorAgent
from sqlalchemy import select


async def setup_orchestrator():
    """Initialize orchestrator with all agents"""
    orchestrator = ResearchRequestOrchestrator()

    # Register all agents
    orchestrator.register_agent('requirements_agent', RequirementsAgent())
    orchestrator.register_agent('phenotype_agent', PhenotypeValidationAgent())
    orchestrator.register_agent('calendar_agent', CalendarAgent())
    orchestrator.register_agent('extraction_agent', DataExtractionAgent())
    orchestrator.register_agent('qa_agent', QualityAssuranceAgent())
    orchestrator.register_agent('delivery_agent', DeliveryAgent())
    orchestrator.register_agent('coordinator_agent', CoordinatorAgent())

    print("✓ Orchestrator initialized with all agents")
    return orchestrator


async def find_stuck_requests():
    """Find requests stuck in early states"""
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).where(
                ResearchRequest.current_state.in_([
                    'new_request',
                    'requirements_gathering'
                ])
            ).order_by(ResearchRequest.created_at)
        )
        stuck_requests = result.scalars().all()
        return stuck_requests


async def process_stuck_request(orchestrator, request):
    """Process a single stuck request"""
    print(f"\n📋 Processing: {request.id}")
    print(f"   Researcher: {request.researcher_name}")
    print(f"   State: {request.current_state}")
    print(f"   Created: {request.created_at}")

    try:
        # Build context
        context = {
            "request_id": request.id,
            "initial_request": request.initial_request,
            "researcher_info": {
                "name": request.researcher_name,
                "email": request.researcher_email,
                "department": request.researcher_department,
                "irb_number": request.irb_number
            }
        }

        # Route to requirements agent
        await orchestrator.route_task(
            agent_id="requirements_agent",
            task="gather_requirements",
            context=context,
            from_agent="process_stuck_script"
        )

        print(f"   ✓ Workflow triggered")
        return True

    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        return False


async def main():
    """Main processing function"""
    print("=" * 60)
    print("PROCESS STUCK REQUESTS")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Initialize database
    await init_db()
    print("✓ Database initialized\n")

    # Setup orchestrator
    orchestrator = await setup_orchestrator()
    print()

    # Find stuck requests
    print("Searching for stuck requests...")
    stuck_requests = await find_stuck_requests()

    if not stuck_requests:
        print("✓ No stuck requests found!")
        return

    print(f"Found {len(stuck_requests)} stuck requests\n")

    # Ask for confirmation
    print("This will trigger the workflow for these requests.")
    response = input("Continue? (y/n): ")

    if response.lower() != 'y':
        print("Cancelled")
        return

    print("\nProcessing requests...")

    # Process each request
    success_count = 0
    failed_count = 0

    for request in stuck_requests:
        result = await process_stuck_request(orchestrator, request)
        if result:
            success_count += 1
        else:
            failed_count += 1

        # Wait a bit between requests to avoid overwhelming the system
        await asyncio.sleep(1)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total processed: {len(stuck_requests)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {failed_count}")

    if success_count > 0:
        print("\n✓ Workflows triggered successfully!")
        print("\nNext steps:")
        print("  1. Monitor the admin dashboard for new approvals")
        print("  2. Check request status: GET /research/{request_id}")
        print("  3. Approvals should appear at: /approvals/pending")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
