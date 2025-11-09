"""
List all research requests in the database
"""

import asyncio
import sys
import os
from sqlalchemy import select

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import get_db_session
from app.database.models import ResearchRequest


async def list_requests():
    """List all requests in database"""
    async with get_db_session() as session:
        result = await session.execute(
            select(ResearchRequest).order_by(ResearchRequest.created_at.desc())
        )
        requests = result.scalars().all()

        print(f"\nFound {len(requests)} research requests in database:\n")
        print("=" * 120)

        for idx, req in enumerate(requests, 1):
            print(f"{idx}. Request ID: {req.id}")
            print(f"   Created: {req.created_at}")
            print(f"   Updated: {req.updated_at}")
            print(f"   Current State: {req.current_state}")
            print(f"   Current Agent: {req.current_agent}")
            print(f"   Researcher: {req.researcher_name} ({req.researcher_email})")
            print(f"   IRB: {req.irb_number}")
            print(f"   Completed: {req.completed_at}")
            print("-" * 120)


async def main():
    await list_requests()


if __name__ == "__main__":
    asyncio.run(main())
