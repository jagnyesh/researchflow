"""
Quick test script for new orchestrator methods
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.orchestrator import ResearchRequestOrchestrator
from app.database import get_db_session, ResearchRequest, Approval
from sqlalchemy import select


async def test_get_requests_by_researcher():
    """Test the new get_requests_by_researcher method"""
    print("\n=== Testing get_requests_by_researcher ===")

    orchestrator = ResearchRequestOrchestrator()

    # Get a sample researcher email from database
    async with get_db_session() as session:
        result = await session.execute(select(ResearchRequest).limit(1))
        sample_request = result.scalar_one_or_none()

        if not sample_request:
            print("❌ No requests in database to test with")
            return False

        researcher_email = sample_request.researcher_email
        print(f"Testing with researcher email: {researcher_email}")

    # Test the method
    try:
        requests = await orchestrator.get_requests_by_researcher(researcher_email)
        print(f"✅ Found {len(requests)} request(s) for researcher")

        if requests:
            for req in requests[:3]:  # Show first 3
                print(f"  - Request {req['request_id']}: {req['current_state']}")

        return True
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


async def test_get_approval_history():
    """Test the new get_approval_history method"""
    print("\n=== Testing get_approval_history ===")

    orchestrator = ResearchRequestOrchestrator()

    # Get a sample request ID
    async with get_db_session() as session:
        result = await session.execute(select(ResearchRequest).limit(1))
        sample_request = result.scalar_one_or_none()

        if not sample_request:
            print("❌ No requests in database to test with")
            return False

        request_id = sample_request.id
        print(f"Testing with request ID: {request_id}")

    # Test the method
    try:
        approvals = await orchestrator.get_approval_history(request_id)
        print(f"✅ Found {len(approvals)} approval(s) for request")

        if approvals:
            for approval in approvals:
                print(
                    f"  - {approval['approval_type']}: {approval['status']} (reviewed by {approval.get('reviewed_by', 'N/A')})"
                )
        else:
            print("  (No approvals for this request yet - this is normal for new requests)")

        return True
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False


async def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing New Orchestrator Methods")
    print("=" * 60)

    test1 = await test_get_requests_by_researcher()
    test2 = await test_get_approval_history()

    print("\n" + "=" * 60)
    print("Test Results:")
    print(f"  get_requests_by_researcher: {'✅ PASS' if test1 else '❌ FAIL'}")
    print(f"  get_approval_history: {'✅ PASS' if test2 else '❌ FAIL'}")
    print("=" * 60)

    if test1 and test2:
        print("\n✅ All tests passed!")
        return 0
    else:
        print("\n❌ Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
