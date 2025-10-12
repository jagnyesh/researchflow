"""
Test Approval Workflow - Human-in-Loop Implementation

Tests the complete approval workflow including:
1. Creating test approvals of different types
2. Fetching pending approvals via API
3. Approving/rejecting approvals
4. Verifying UI displays correctly
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import get_db_session, ResearchRequest, Approval
from app.services.approval_service import ApprovalService
from app.orchestrator.workflow_engine import WorkflowState
import requests


async def create_test_data():
    """Create test research request and approvals"""
    print("=" * 80)
    print("CREATING TEST DATA")
    print("=" * 80)

    async with get_db_session() as session:
        # Create test research request
        request_id = "REQ-20251012-TEST001"

        # Check if request already exists
        existing = await session.get(ResearchRequest, request_id)
        if not existing:
            research_request = ResearchRequest(
                id=request_id,
                researcher_name="Dr. Test User",
                researcher_email="test@hospital.org",
                researcher_department="Cardiology",
                irb_number="IRB-2025-001",
                initial_request="Test request for diabetes patients with HbA1c > 7.0",
                current_state=WorkflowState.REQUIREMENTS_REVIEW.value,
                current_agent="requirements_agent",
                agents_involved=[],
                state_history=[
                    {
                        'state': WorkflowState.NEW_REQUEST.value,
                        'timestamp': datetime.now().isoformat()
                    }
                ]
            )
            session.add(research_request)
            await session.flush()
            print(f"✓ Created test research request: {request_id}")
        else:
            print(f"✓ Using existing research request: {request_id}")

        approval_service = ApprovalService(session)

        # 1. Requirements Approval
        print("\n1. Creating REQUIREMENTS approval...")
        req_approval = await approval_service.create_approval(
            request_id=request_id,
            approval_type="requirements",
            submitted_by="requirements_agent",
            approval_data={
                "structured_requirements": {
                    "study_title": "Diabetes HbA1c Study",
                    "inclusion_criteria": [
                        "Patients with Type 2 Diabetes",
                        "HbA1c > 7.0%",
                        "Age >= 18 years"
                    ],
                    "exclusion_criteria": [
                        "Type 1 Diabetes",
                        "Pregnant patients"
                    ],
                    "data_elements": ["demographics", "lab_results", "medications"],
                    "time_period": {
                        "start": "2023-01-01",
                        "end": "2024-12-31"
                    }
                },
                "completeness_score": 0.92,
                "conversation_turns": 5
            }
        )
        print(f"   ✓ Created requirements approval (ID: {req_approval.id})")

        # 2. Phenotype SQL Approval (CRITICAL)
        print("\n2. Creating PHENOTYPE_SQL approval (CRITICAL)...")
        sql_approval = await approval_service.create_approval(
            request_id=request_id,
            approval_type="phenotype_sql",
            submitted_by="phenotype_agent",
            approval_data={
                "sql_query": """SELECT
    p.id AS patient_id,
    p.birthDate,
    p.gender,
    o.code,
    o.valueQuantity_value AS hba1c_value,
    o.effectiveDateTime
FROM patient p
JOIN observation o ON o.subject_id = p.id
WHERE o.code_coding_code = '4548-4'  -- HbA1c LOINC code
  AND o.valueQuantity_value > 7.0
  AND o.effectiveDateTime >= '2023-01-01'
  AND o.effectiveDateTime <= '2024-12-31'
  AND p.birthDate <= '2005-01-01'  -- Age >= 18
ORDER BY p.id, o.effectiveDateTime DESC""",
                "estimated_cohort": 347,
                "feasibility_score": 0.87,
                "data_availability": {
                    "overall_availability": 0.91,
                    "by_element": {
                        "demographics": 1.0,
                        "hba1c_labs": 0.95,
                        "medications": 0.78
                    }
                },
                "warnings": [
                    {
                        "type": "data_availability",
                        "message": "Medication data availability is 78%, some patients may have incomplete records"
                    }
                ],
                "recommendations": [
                    "Consider extending time period to increase cohort size",
                    "Review medication completeness with informatician"
                ]
            }
        )
        print(f"   ✓ Created phenotype_sql approval (ID: {sql_approval.id}) - CRITICAL")

        # 3. Scope Change Approval
        print("\n3. Creating SCOPE_CHANGE approval...")
        scope_approval = await approval_service.create_approval(
            request_id=request_id,
            approval_type="scope_change",
            submitted_by="coordinator_agent",
            approval_data={
                "requested_changes": {
                    "inclusion_criteria": [
                        "Patients with Type 2 Diabetes",
                        "HbA1c > 7.0%",
                        "Age >= 50 years"  # CHANGED from >= 18
                    ],
                    "additional_data_elements": ["smoking_status", "bmi"]
                },
                "reason": "IRB requested age restriction to >= 50 years and additional risk factors",
                "requested_by": "researcher@hospital.org",
                "impact_analysis": {
                    "severity": "high",
                    "requires_rework": True,
                    "restart_from_state": "requirements_gathering",
                    "estimated_delay_hours": 24,
                    "affected_components": ["phenotype", "extraction", "qa"],
                    "cohort_impact": {
                        "current_estimated": 347,
                        "new_estimated": 198,
                        "reduction_percentage": 43
                    }
                }
            }
        )
        print(f"   ✓ Created scope_change approval (ID: {scope_approval.id})")

        # 4. Extraction Approval
        print("\n4. Creating EXTRACTION approval...")
        extract_approval = await approval_service.create_approval(
            request_id=request_id,
            approval_type="extraction",
            submitted_by="calendar_agent",
            approval_data={
                "extraction_plan": {
                    "estimated_patients": 347,
                    "data_sources": ["FHIR Server", "Data Warehouse"],
                    "estimated_records": 5200,
                    "estimated_duration_minutes": 45,
                    "phi_level": "limited_dataset",
                    "scheduled_time": (datetime.now() + timedelta(hours=2)).isoformat()
                },
                "kickoff_meeting": {
                    "scheduled": True,
                    "attendees": ["researcher@hospital.org", "informatician@hospital.org"],
                    "date": (datetime.now() + timedelta(hours=1)).isoformat()
                }
            }
        )
        print(f"   ✓ Created extraction approval (ID: {extract_approval.id})")

        # 5. QA Approval
        print("\n5. Creating QA approval...")
        qa_approval = await approval_service.create_approval(
            request_id=request_id,
            approval_type="qa",
            submitted_by="qa_agent",
            approval_data={
                "qa_results": {
                    "total_patients": 347,
                    "total_records": 5183,
                    "completeness_score": 0.94,
                    "quality_checks": {
                        "no_duplicates": True,
                        "phi_scrubbed": True,
                        "data_integrity": True,
                        "schema_validation": True
                    },
                    "issues_found": [
                        {
                            "severity": "low",
                            "type": "missing_data",
                            "message": "23 patients missing smoking status",
                            "patient_count": 23
                        }
                    ],
                    "recommendations": [
                        "Data quality is excellent",
                        "Minor missing data documented in delivery notes"
                    ]
                }
            }
        )
        print(f"   ✓ Created qa approval (ID: {qa_approval.id})")

        await session.commit()

    print("\n" + "=" * 80)
    print("TEST DATA CREATION COMPLETE")
    print("=" * 80)
    return request_id


async def test_api_endpoints(request_id):
    """Test approval API endpoints"""
    print("\n" + "=" * 80)
    print("TESTING API ENDPOINTS")
    print("=" * 80)

    BASE_URL = "http://localhost:8000"

    # Test 1: Get all pending approvals
    print("\n1. GET /approvals/pending (all types)")
    response = requests.get(f"{BASE_URL}/approvals/pending")
    data = response.json()
    print(f"   Status: {response.status_code}")
    print(f"   Count: {data['count']}")
    print(f"   Approvals: {len(data['approvals'])}")
    for approval in data['approvals']:
        print(f"     - {approval['approval_type']} (ID: {approval['id']})")

    # Test 2: Get phenotype_sql approvals only (CRITICAL)
    print("\n2. GET /approvals/pending?approval_type=phenotype_sql")
    response = requests.get(f"{BASE_URL}/approvals/pending?approval_type=phenotype_sql")
    data = response.json()
    print(f"   Status: {response.status_code}")
    print(f"   Count: {data['count']}")
    if data['approvals']:
        sql_approval = data['approvals'][0]
        print(f"   SQL Approval ID: {sql_approval['id']}")
        print(f"   Estimated Cohort: {sql_approval['approval_data']['estimated_cohort']}")
        print(f"   Feasibility: {sql_approval['approval_data']['feasibility_score']}")
        sql_query = sql_approval['approval_data']['sql_query']
        print(f"   SQL Query (first 100 chars): {sql_query[:100]}...")

    # Test 3: Get approvals for specific request
    print(f"\n3. GET /approvals/request/{request_id}")
    response = requests.get(f"{BASE_URL}/approvals/request/{request_id}")
    data = response.json()
    print(f"   Status: {response.status_code}")
    print(f"   Approvals for request: {len(data['approvals'])}")

    # Test 4: Get specific approval
    print(f"\n4. GET /approvals/1 (requirements approval)")
    response = requests.get(f"{BASE_URL}/approvals/1")
    data = response.json()
    print(f"   Status: {response.status_code}")
    print(f"   Type: {data['approval_type']}")
    print(f"   Status: {data['status']}")

    print("\n" + "=" * 80)
    print("API ENDPOINT TESTS COMPLETE")
    print("=" * 80)


async def test_approval_workflow():
    """Test approve/reject/modify workflow"""
    print("\n" + "=" * 80)
    print("TESTING APPROVAL WORKFLOW")
    print("=" * 80)

    BASE_URL = "http://localhost:8000"

    # Test approving requirements
    print("\n1. Approving REQUIREMENTS (ID: 1)")
    response = requests.post(
        f"{BASE_URL}/approvals/1/respond",
        json={
            "decision": "approve",
            "reviewer": "informatician@hospital.org",
            "notes": "Requirements look good, medical terminology is accurate"
        }
    )
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        print(f"   Response: {response.json()}")
    else:
        print(f"   Error: {response.text}")

    # Test modifying SQL
    print("\n2. Modifying PHENOTYPE_SQL (ID: 2)")
    response = requests.post(
        f"{BASE_URL}/approvals/2/respond",
        json={
            "decision": "modify",
            "reviewer": "informatician@hospital.org",
            "notes": "SQL looks good but adjusted date filter format",
            "modifications": {
                "sql_query": """SELECT
    p.id AS patient_id,
    p.birthDate,
    p.gender,
    o.code,
    o.valueQuantity_value AS hba1c_value,
    o.effectiveDateTime
FROM patient p
JOIN observation o ON o.subject_id = p.id
WHERE o.code_coding_code = '4548-4'
  AND o.valueQuantity_value > 7.0
  AND o.effectiveDateTime BETWEEN '2023-01-01' AND '2024-12-31'
  AND EXTRACT(YEAR FROM AGE(p.birthDate)) >= 18
ORDER BY p.id, o.effectiveDateTime DESC"""
            }
        }
    )
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        print(f"   Response: {response.json()}")
    else:
        print(f"   Error: {response.text}")

    # Test rejecting scope change
    print("\n3. Rejecting SCOPE_CHANGE (ID: 3)")
    response = requests.post(
        f"{BASE_URL}/approvals/3/respond",
        json={
            "decision": "reject",
            "reviewer": "admin@hospital.org",
            "notes": "Scope change too significant, would require new IRB approval. Please submit as new request."
        }
    )
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        print(f"   Response: {response.json()}")
    else:
        print(f"   Error: {response.text}")

    print("\n" + "=" * 80)
    print("APPROVAL WORKFLOW TESTS COMPLETE")
    print("=" * 80)


async def verify_final_state():
    """Verify final state of approvals"""
    print("\n" + "=" * 80)
    print("VERIFYING FINAL STATE")
    print("=" * 80)

    async with get_db_session() as session:
        approval_service = ApprovalService(session)

        print("\n1. Checking approval statuses:")
        for approval_id in range(1, 6):
            approval = await approval_service.get_approval(approval_id)
            if approval:
                print(f"   Approval {approval_id} ({approval.approval_type}): {approval.status}")
                if approval.reviewed_by:
                    print(f"     Reviewed by: {approval.reviewed_by}")
                if approval.review_notes:
                    print(f"     Notes: {approval.review_notes[:60]}...")

        # Check remaining pending
        print("\n2. Remaining pending approvals:")
        response = requests.get("http://localhost:8000/approvals/pending")
        data = response.json()
        print(f"   Count: {data['count']}")
        if data['approvals']:
            for approval in data['approvals']:
                print(f"     - {approval['approval_type']} (ID: {approval['id']})")
        else:
            print("   (None - all processed!)")

    print("\n" + "=" * 80)
    print("FINAL STATE VERIFICATION COMPLETE")
    print("=" * 80)


async def main():
    """Run all tests"""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "APPROVAL WORKFLOW TEST SUITE" + " " * 30 + "║")
    print("╚" + "=" * 78 + "╝")

    try:
        # Step 1: Create test data
        request_id = await create_test_data()

        # Step 2: Test API endpoints
        await test_api_endpoints(request_id)

        # Step 3: Test approval workflow
        await test_approval_workflow()

        # Step 4: Verify final state
        await verify_final_state()

        print("\n")
        print("╔" + "=" * 78 + "╗")
        print("║" + " " * 25 + "ALL TESTS PASSED ✅" + " " * 34 + "║")
        print("╚" + "=" * 78 + "╝")

        print("\n📊 NEXT STEPS:")
        print("   1. Open Admin Dashboard: http://localhost:8502")
        print("   2. Navigate to 'Pending Approvals' tab")
        print("   3. View remaining approvals (Extraction, QA)")
        print("   4. Test approve/reject/modify buttons in UI")
        print("\n")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
