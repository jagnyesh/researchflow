"""
Diagnostic Script: Approval Dashboard Issue

This script diagnoses why approvals may not be showing up in the admin dashboard.
It checks:
1. Database connectivity
2. Approval records in database
3. API endpoint connectivity
4. Orchestrator state
"""

import asyncio
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import get_db_session, init_db
from app.database.models import Approval, ResearchRequest, AgentExecution
from sqlalchemy import select, func
import requests


async def check_database():
    """Check database for approvals"""
    print("=" * 60)
    print("1. DATABASE CHECK")
    print("=" * 60)

    try:
        async with get_db_session() as session:
            # Count total approvals
            result = await session.execute(select(func.count()).select_from(Approval))
            total_approvals = result.scalar()
            print(f"✓ Database connected")
            print(f"  Total approvals in database: {total_approvals}")

            # Count pending approvals
            result = await session.execute(
                select(func.count()).select_from(Approval).where(Approval.status == 'pending')
            )
            pending_count = result.scalar()
            print(f"  Pending approvals: {pending_count}")

            if pending_count > 0:
                # Get pending approvals
                result = await session.execute(
                    select(Approval)
                    .where(Approval.status == 'pending')
                    .order_by(Approval.submitted_at)
                )
                pending_approvals = result.scalars().all()

                print(f"\n  Pending Approval Details:")
                for approval in pending_approvals:
                    age = datetime.now() - approval.submitted_at
                    print(f"    - ID: {approval.id}")
                    print(f"      Type: {approval.approval_type}")
                    print(f"      Request: {approval.request_id}")
                    print(f"      Submitted: {approval.submitted_at.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"      Age: {age.total_seconds()/3600:.1f} hours")
                    print(f"      Submitted by: {approval.submitted_by}")
                    print()

            # Check for approved/rejected approvals
            for status in ['approved', 'rejected', 'modified']:
                result = await session.execute(
                    select(func.count()).select_from(Approval).where(Approval.status == status)
                )
                count = result.scalar()
                print(f"  {status.capitalize()} approvals: {count}")

            return True

    except Exception as e:
        print(f"❌ Database error: {str(e)}")
        return False


async def check_requests():
    """Check research requests status"""
    print("\n" + "=" * 60)
    print("2. REQUEST STATUS CHECK")
    print("=" * 60)

    try:
        async with get_db_session() as session:
            # Get active requests
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.completed_at.is_(None))
            )
            active_requests = result.scalars().all()

            print(f"✓ Active research requests: {len(active_requests)}")

            if len(active_requests) > 0:
                print(f"\n  Request States:")
                state_counts = {}
                for req in active_requests:
                    state = req.current_state
                    state_counts[state] = state_counts.get(state, 0) + 1

                for state, count in sorted(state_counts.items()):
                    print(f"    - {state}: {count}")

                # Show sample of requests waiting for approval
                approval_states = [
                    'requirements_review',
                    'phenotype_review',
                    'extraction_approval',
                    'qa_review',
                    'scope_change'
                ]

                waiting_for_approval = [req for req in active_requests if req.current_state in approval_states]

                if waiting_for_approval:
                    print(f"\n  Requests waiting for approval ({len(waiting_for_approval)}):")
                    for req in waiting_for_approval[:5]:  # Show first 5
                        print(f"    - {req.id}")
                        print(f"      State: {req.current_state}")
                        print(f"      Researcher: {req.researcher_name}")
                        print(f"      Created: {req.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

            return True

    except Exception as e:
        print(f"❌ Request check error: {str(e)}")
        return False


def check_api():
    """Check API endpoint"""
    print("\n" + "=" * 60)
    print("3. API ENDPOINT CHECK")
    print("=" * 60)

    api_base = os.getenv("API_BASE_URL", "http://localhost:8000")

    try:
        # Check root endpoint
        response = requests.get(f"{api_base}/", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✓ API server is running at {api_base}")
            print(f"  Version: {data.get('version', 'unknown')}")
            print(f"  Orchestrator initialized: {data.get('orchestrator_initialized', False)}")
        else:
            print(f"⚠ API returned status {response.status_code}")

        # Check approvals endpoint
        response = requests.get(f"{api_base}/approvals/pending", timeout=5)
        if response.status_code == 200:
            data = response.json()
            count = data.get('count', 0)
            print(f"✓ Approvals endpoint working")
            print(f"  Pending approvals returned by API: {count}")

            if count > 0:
                approvals = data.get('approvals', [])
                print(f"\n  Approval Types:")
                type_counts = {}
                for approval in approvals:
                    type_name = approval.get('approval_type', 'unknown')
                    type_counts[type_name] = type_counts.get(type_name, 0) + 1

                for type_name, count in sorted(type_counts.items()):
                    print(f"    - {type_name}: {count}")
            else:
                print(f"  ⚠ API returns 0 pending approvals (but database may have them)")

        else:
            print(f"❌ Approvals endpoint error: {response.status_code}")
            print(f"   Response: {response.text[:200]}")

        return True

    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to API at {api_base}")
        print(f"   Make sure the API server is running:")
        print(f"   > uvicorn app.main:app --reload --port 8000")
        return False

    except Exception as e:
        print(f"❌ API check error: {str(e)}")
        return False


async def check_agent_activity():
    """Check recent agent activity"""
    print("\n" + "=" * 60)
    print("4. AGENT ACTIVITY CHECK")
    print("=" * 60)

    try:
        async with get_db_session() as session:
            # Get recent agent executions
            result = await session.execute(
                select(AgentExecution)
                .order_by(AgentExecution.started_at.desc())
                .limit(10)
            )
            recent_executions = result.scalars().all()

            if recent_executions:
                print(f"✓ Recent agent executions: {len(recent_executions)}")
                print(f"\n  Last 10 agent executions:")

                for exec in recent_executions:
                    age = datetime.now() - exec.started_at
                    status_emoji = "✓" if exec.status == "success" else "✗" if exec.status == "failed" else "⏳"

                    print(f"    {status_emoji} {exec.agent_id}.{exec.task}")
                    print(f"       Request: {exec.request_id}")
                    print(f"       Time: {exec.started_at.strftime('%H:%M:%S')} ({age.total_seconds()/60:.1f}m ago)")
                    print(f"       Status: {exec.status}")
                    if exec.error:
                        print(f"       Error: {exec.error[:80]}...")
                    print()
            else:
                print(f"⚠ No agent executions found")
                print(f"  This suggests agents are not running or no requests have been processed")

            return True

    except Exception as e:
        print(f"❌ Agent activity check error: {str(e)}")
        return False


async def diagnose_specific_issue():
    """Diagnose the specific issue: new approvals not appearing"""
    print("\n" + "=" * 60)
    print("5. SPECIFIC ISSUE DIAGNOSIS")
    print("=" * 60)

    try:
        async with get_db_session() as session:
            # Check if there are requests in "new_request" state
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.current_state == 'new_request')
            )
            new_requests = result.scalars().all()

            if new_requests:
                print(f"⚠ Found {len(new_requests)} requests stuck in 'new_request' state")
                print(f"  This suggests the workflow is not progressing")
                print(f"\n  Possible causes:")
                print(f"    1. Orchestrator not running")
                print(f"    2. Agents not registered properly")
                print(f"    3. LLM API key missing or invalid")
                print()

            # Check if there are requests that transitioned but no approval created
            result = await session.execute(
                select(ResearchRequest)
                .where(ResearchRequest.current_state.in_([
                    'requirements_review',
                    'phenotype_review',
                    'extraction_approval',
                    'qa_review'
                ]))
            )
            requests_in_approval_state = result.scalars().all()

            for req in requests_in_approval_state:
                # Check if approval exists
                approval_result = await session.execute(
                    select(Approval)
                    .where(Approval.request_id == req.id)
                    .where(Approval.status == 'pending')
                )
                approval = approval_result.scalar_one_or_none()

                if not approval:
                    print(f"⚠ ISSUE FOUND: Request {req.id} is in '{req.current_state}' but has NO pending approval")
                    print(f"  This is a bug - approval should have been created")
                    print(f"  Researcher: {req.researcher_name}")
                    print(f"  State: {req.current_state}")
                    print()

            # Check recent transitions to approval states
            result = await session.execute(
                select(ResearchRequest)
                .order_by(ResearchRequest.created_at.desc())
                .limit(20)
            )
            recent_requests = result.scalars().all()

            approval_created_count = 0
            for req in recent_requests:
                if 'review' in req.current_state or 'approval' in req.current_state:
                    approval_result = await session.execute(
                        select(Approval).where(Approval.request_id == req.id)
                    )
                    approval = approval_result.scalar_one_or_none()
                    if approval:
                        approval_created_count += 1

            if approval_created_count > 0:
                print(f"✓ Found {approval_created_count} requests with approvals in recent history")
                print(f"  Approval workflow appears to be working")
            else:
                print(f"⚠ No approvals found in recent requests")
                print(f"  Possible causes:")
                print(f"    1. Agents not returning 'requires_approval' flag")
                print(f"    2. Orchestrator not handling approval requests")
                print(f"    3. ApprovalService not creating records")

            return True

    except Exception as e:
        print(f"❌ Diagnosis error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all diagnostics"""
    print("\n" + "=" * 60)
    print("RESEARCHFLOW APPROVAL DASHBOARD DIAGNOSTIC")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Initialize database
    await init_db()

    # Run all checks
    results = []

    results.append(await check_database())
    results.append(await check_requests())
    results.append(check_api())
    results.append(await check_agent_activity())
    results.append(await diagnose_specific_issue())

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(results)
    total = len(results)

    print(f"Checks passed: {passed}/{total}")

    if passed == total:
        print("\n✓ All checks passed!")
        print("\nIf approvals still don't appear in dashboard:")
        print("  1. Try hard refreshing the dashboard (Ctrl+Shift+R)")
        print("  2. Check browser console for errors")
        print("  3. Verify API_BASE_URL in dashboard matches actual API server")
    else:
        print("\n⚠ Some checks failed - see details above")
        print("\nNext steps:")
        print("  1. Fix any errors shown in the checks above")
        print("  2. Ensure API server is running: uvicorn app.main:app --reload --port 8000")
        print("  3. Ensure database migrations are up to date")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
