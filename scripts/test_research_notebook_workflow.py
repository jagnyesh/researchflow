#!/usr/bin/env python3
"""
Test Research Notebook Workflow

Tests the two-stage workflow:
1. Submit research request with pre-structured requirements
2. Process request with skip_conversation=True
3. Verify approval is created
4. Verify request appears in Admin Dashboard
"""

import asyncio
import httpx
from datetime import datetime

API_BASE_URL = "http://localhost:8000"


async def test_research_notebook_workflow():
    """Test the complete Research Notebook workflow"""

    print("=" * 80)
    print("Testing Research Notebook Workflow")
    print("=" * 80)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Submit research request with pre-structured requirements
        print("\n[Step 1] Submitting research request with structured requirements...")

        structured_requirements = {
            "study_title": f"Test Research Notebook Query - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "principal_investigator": "Research Notebook User",
            "inclusion_criteria": [
                {
                    "description": "Patients with diabetes",
                    "concepts": ["diabetes"],
                    "codes": []
                }
            ],
            "exclusion_criteria": [],
            "data_elements": ["demographics", "conditions", "labs"],
            "time_period": {
                "start": "2023-01-01",
                "end": "2023-12-31"
            },
            "estimated_cohort_size": 5,
            "delivery_format": "CSV",
            "phi_level": "de-identified"
        }

        submit_response = await client.post(
            f"{API_BASE_URL}/research/submit",
            json={
                "researcher_name": "Test User",
                "researcher_email": "test@hospital.org",
                "researcher_department": "Clinical Research",
                "irb_number": "IRB-TEST-001",
                "initial_request": "Test query for patients with diabetes",
                "structured_requirements": structured_requirements
            }
        )

        submit_response.raise_for_status()
        submit_result = submit_response.json()
        request_id = submit_result.get("request_id")

        print(f"✅ Research request submitted: {request_id}")
        print(f"   Status: {submit_result.get('status')}")

        # Step 2: Process the request with pre-structured requirements
        print(f"\n[Step 2] Processing request with skip_conversation=True...")

        process_response = await client.post(
            f"{API_BASE_URL}/research/process/{request_id}",
            json={
                "structured_requirements": structured_requirements,
                "skip_conversation": True
            }
        )

        process_response.raise_for_status()
        process_result = process_response.json()

        print(f"✅ Processing started")
        print(f"   Agent: {process_result.get('agent')}")
        print(f"   Task: {process_result.get('task')}")
        print(f"   Result: {process_result.get('result', {})}")

        # Wait a moment for async processing
        print("\n[Waiting] Allowing time for approval creation...")
        await asyncio.sleep(2)

        # Step 3: Check if approval was created
        print(f"\n[Step 3] Checking for approval creation...")

        approvals_response = await client.get(
            f"{API_BASE_URL}/approvals/request/{request_id}"
        )
        approvals_response.raise_for_status()
        approvals_result = approvals_response.json()

        approvals = approvals_result.get("approvals", [])
        approval_count = len(approvals)

        if approval_count > 0:
            print(f"✅ {approval_count} approval(s) created!")
            for approval in approvals:
                print(f"   - Approval ID: {approval.get('id')}")
                print(f"     Type: {approval.get('approval_type')}")
                print(f"     Status: {approval.get('status')}")
                print(f"     Submitted By: {approval.get('submitted_by')}")
        else:
            print("❌ No approvals created")
            print("   This indicates the requirements agent did not complete successfully")

        # Step 4: Check if request appears in pending approvals list
        print(f"\n[Step 4] Checking pending approvals endpoint...")

        pending_response = await client.get(f"{API_BASE_URL}/approvals/pending")
        pending_response.raise_for_status()
        pending_result = pending_response.json()

        pending_approvals = pending_result.get("approvals", [])
        our_approvals = [a for a in pending_approvals if a.get("request_id") == request_id]

        if our_approvals:
            print(f"✅ Request found in pending approvals (count: {len(our_approvals)})")
            for approval in our_approvals:
                print(f"   - Type: {approval.get('approval_type')}")
                print(f"     Status: {approval.get('status')}")
        else:
            print("❌ Request NOT found in pending approvals")

        # Step 5: Get final request status
        print(f"\n[Step 5] Checking final request status...")

        status_response = await client.get(f"{API_BASE_URL}/research/{request_id}")
        status_response.raise_for_status()
        status_result = status_response.json()

        print(f"✅ Final request status:")
        print(f"   Request ID: {status_result.get('request_id')}")
        print(f"   Current State: {status_result.get('current_state')}")
        print(f"   Current Agent: {status_result.get('current_agent')}")
        print(f"   Agents Involved: {status_result.get('agents_involved', [])}")

        # Summary
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)

        success = approval_count > 0 and len(our_approvals) > 0

        if success:
            print("✅ ALL TESTS PASSED")
            print(f"   - Request created: {request_id}")
            print(f"   - Approvals created: {approval_count}")
            print(f"   - Pending approvals visible: {len(our_approvals)}")
            print(f"   - Final state: {status_result.get('current_state')}")
        else:
            print("❌ TESTS FAILED")
            if approval_count == 0:
                print("   - No approvals were created")
            if len(our_approvals) == 0:
                print("   - Request not visible in pending approvals")

        print("=" * 80)

        return success


if __name__ == "__main__":
    success = asyncio.run(test_research_notebook_workflow())
    exit(0 if success else 1)
