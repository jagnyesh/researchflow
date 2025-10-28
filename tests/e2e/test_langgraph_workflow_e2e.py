"""
End-to-End Integration Tests - LangGraph Workflow (Direct)

Tests LangGraph workflow directly with PostgreSQL database, bypassing FastAPI layer.

Test Scenarios:
1. Happy Path - Full workflow from new_request → complete (with simulated approvals)
2. State Persistence - Save workflow state, load from DB, resume from checkpoint

Requirements:
- Docker PostgreSQL running on localhost:5434
- ANTHROPIC_API_KEY in environment (for real LLM calls)
- Database initialized with schema
"""

import pytest
import asyncio
import time
from datetime import datetime
from pathlib import Path
import json
import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.langchain_orchestrator.langgraph_workflow import FullWorkflow
from app.langchain_orchestrator.persistence import WorkflowPersistence
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# ============================================================================
# Configuration
# ============================================================================

DATABASE_URL = "postgresql+asyncpg://researchflow:researchflow@localhost:5434/researchflow"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def persistence():
    """Create persistence layer"""
    return WorkflowPersistence(database_url=DATABASE_URL)


@pytest.fixture
def test_request_data():
    """Load test request data from fixtures"""
    fixture_path = Path(__file__).parent / "fixtures" / "sample_diabetes_request.json"
    with open(fixture_path, 'r') as f:
        return json.load(f)


@pytest.fixture
def workflow():
    """Create fresh workflow instance"""
    return FullWorkflow()


# ============================================================================
# Test: Happy Path - Complete Workflow
# ============================================================================

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_happy_path_langgraph_workflow(workflow, persistence, test_request_data):
    """
    Test complete LangGraph workflow from new_request to complete

    This test simulates the full workflow with automatic approvals at each gate.
    It tests the actual production LangGraph code with PostgreSQL persistence.

    Expected Duration: 2-3 minutes (includes real LLM calls)
    Expected Cost: ~$1-2 (Claude API)
    """
    print("\\n" + "=" * 80)
    print("TEST: Happy Path - LangGraph Workflow E2E (Direct)")
    print("=" * 80)

    start_time = time.time()

    # ===== Step 1: Create Initial State =====
    print("\\n[1/11] Creating initial workflow state...")

    request_id = f"REQ-E2E-{int(time.time())}"

    # Create initial state
    initial_state = await persistence.create_initial_state(
        request_id=request_id,
        researcher_request=test_request_data["initial_request"],
        researcher_info=test_request_data["researcher_info"]
    )

    print(f"  ✓ Initial state created: {request_id}")
    print(f"  ✓ Current state: {initial_state['current_state']}")

    # ===== Step 2: Process New Request =====
    print("\\n[2/11] Processing new request...")

    state_after_new_request = await workflow.run(initial_state)

    print(f"  ✓ State after new_request: {state_after_new_request['current_state']}")
    assert state_after_new_request['current_state'] in ['requirements_gathering', 'wait_for_input']

    # ===== Step 3: Submit Requirements (Bypass Conversation) =====
    print("\\n[3/11] Submitting structured requirements...")

    # Update state with structured requirements
    state_with_requirements = {
        **state_after_new_request,
        'requirements': test_request_data["structured_requirements"],
        'requirements_complete': True,
        'completeness_score': 1.0
    }

    # Process requirements_gathering
    state_after_requirements = await workflow.run(state_with_requirements)

    print(f"  ✓ State after requirements_gathering: {state_after_requirements['current_state']}")
    assert state_after_requirements['current_state'] == 'requirements_review'

    # ===== Step 4: Approve Requirements =====
    print("\\n[4/11] Approving requirements...")

    state_with_approval = {
        **state_after_requirements,
        'requirements_approved': True
    }

    state_after_approval = await workflow.run(state_with_approval)

    print(f"  ✓ State after requirements approval: {state_after_approval['current_state']}")
    assert state_after_approval['current_state'] == 'phenotype_review'

    # ===== Step 5: Verify Feasibility Validation =====
    print("\\n[5/11] Verifying feasibility validation (phenotype SQL generation)...")

    # After requirements approval, workflow should already be at phenotype_review
    # (it automatically processes feasibility_validation in the same run)
    state_after_phenotype = state_after_approval

    print(f"  ✓ Phenotype validation complete")
    print(f"  ✓ Feasibility score: {state_after_phenotype.get('feasibility_score', 'N/A')}")
    print(f"  ✓ Estimated cohort: {state_after_phenotype.get('estimated_cohort_size', 'N/A')}")

    assert state_after_phenotype['current_state'] == 'phenotype_review'
    assert state_after_phenotype.get('phenotype_sql') is not None

    # ===== Step 6: Approve Phenotype SQL =====
    print("\\n[6/11] Approving phenotype SQL...")

    state_with_sql_approval = {
        **state_after_phenotype,
        'phenotype_approved': True
    }

    state_after_sql_approval = await workflow.run(state_with_sql_approval)

    print(f"  ✓ State after phenotype approval: {state_after_sql_approval['current_state']}")
    assert state_after_sql_approval['current_state'] in ['schedule_kickoff', 'extraction_approval']

    # ===== Step 7: Schedule Kickoff Meeting =====
    print("\\n[7/11] Scheduling kickoff meeting...")

    if state_after_sql_approval['current_state'] == 'schedule_kickoff':
        state_after_kickoff = await workflow.run(state_after_sql_approval)
        print(f"  ✓ Kickoff meeting scheduled")
    else:
        state_after_kickoff = state_after_sql_approval

    assert state_after_kickoff['current_state'] == 'extraction_approval'

    # ===== Step 8: Approve Extraction =====
    print("\\n[8/11] Approving data extraction...")

    state_with_extraction_approval = {
        **state_after_kickoff,
        'extraction_approved': True
    }

    state_after_extraction_approval = await workflow.run(state_with_extraction_approval)

    print(f"  ✓ State after extraction approval: {state_after_extraction_approval['current_state']}")
    assert state_after_extraction_approval['current_state'] in ['data_extraction', 'qa_validation', 'qa_review']

    # ===== Step 9: Extract Data =====
    print("\\n[9/11] Extracting data...")

    if state_after_extraction_approval['current_state'] == 'data_extraction':
        state_after_extraction = await workflow.run(state_after_extraction_approval)
        print(f"  ✓ Data extraction complete")
    else:
        state_after_extraction = state_after_extraction_approval

    # ===== Step 10: QA Validation =====
    print("\\n[10/11] Running QA validation...")

    if state_after_extraction['current_state'] == 'qa_validation':
        state_after_qa = await workflow.run(state_after_extraction)
        print(f"  ✓ QA validation complete")
    else:
        state_after_qa = state_after_extraction

    assert state_after_qa['current_state'] == 'qa_review'

    # ===== Step 11: Approve QA and Complete =====
    print("\\n[11/11] Approving QA results and completing delivery...")

    state_with_qa_approval = {
        **state_after_qa,
        'qa_approved': True
    }

    state_after_qa_approval = await workflow.run(state_with_qa_approval)

    if state_after_qa_approval['current_state'] == 'data_delivery':
        final_state = await workflow.run(state_after_qa_approval)
    else:
        final_state = state_after_qa_approval

    print(f"  ✓ Final state: {final_state['current_state']}")

    # ===== Verify Final State =====
    assert final_state['current_state'] == 'complete'
    assert final_state.get('delivered_at') is not None

    elapsed_time = time.time() - start_time

    print("\\n" + "=" * 80)
    print("✅ HAPPY PATH TEST PASSED")
    print("=" * 80)
    print(f"Request ID: {request_id}")
    print(f"Final State: {final_state['current_state']}")
    print(f"Execution Time: {elapsed_time:.2f} seconds")
    print(f"All workflow stages completed successfully")
    print("=" * 80)


# ============================================================================
# Test: State Persistence & Resumption
# ============================================================================

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_persistence_langgraph(workflow, persistence, test_request_data):
    """
    Test workflow state persistence and resumption from database

    Steps:
    1. Start workflow, get to requirements_review
    2. Save state to PostgreSQL
    3. Load state from database
    4. Resume workflow from checkpoint
    5. Complete workflow to verify integrity

    Expected Duration: 2-3 minutes
    """
    print("\\n" + "=" * 80)
    print("TEST: State Persistence & Resumption - LangGraph Workflow")
    print("=" * 80)

    start_time = time.time()

    # ===== Step 1: Start Workflow =====
    print("\\n[1/5] Starting workflow...")

    request_id = f"REQ-PERSIST-{int(time.time())}"

    initial_state = await persistence.create_initial_state(
        request_id=request_id,
        researcher_request=test_request_data["initial_request"],
        researcher_info=test_request_data["researcher_info"]
    )

    print(f"  ✓ Request created: {request_id}")

    # Process to requirements_review
    state_after_new = await workflow.run(initial_state)

    state_with_requirements = {
        **state_after_new,
        'requirements': test_request_data["structured_requirements"],
        'requirements_complete': True,
        'completeness_score': 1.0
    }

    checkpoint_state = await workflow.run(state_with_requirements)

    print(f"  ✓ Workflow at checkpoint: {checkpoint_state['current_state']}")
    assert checkpoint_state['current_state'] == 'requirements_review'

    # ===== Step 2: Save State to Database =====
    print("\\n[2/5] Saving state to PostgreSQL...")

    # State is automatically saved by persistence layer
    print("  ✓ State persisted to database")

    # ===== Step 3: Load State from Database =====
    print("\\n[3/5] Loading state from database...")

    loaded_state = await persistence.load_workflow_state(request_id)

    assert loaded_state is not None
    assert loaded_state['request_id'] == request_id
    assert loaded_state['current_state'] == 'requirements_review'

    print(f"  ✓ State loaded successfully:")
    print(f"    - request_id: {loaded_state['request_id']}")
    print(f"    - current_state: {loaded_state['current_state']}")
    print(f"    - requirements_complete: {loaded_state.get('requirements_complete')}")

    # ===== Step 4: Resume Workflow =====
    print("\\n[4/5] Resuming workflow from checkpoint...")

    resumed_state = {
        **loaded_state,
        'requirements_approved': True
    }

    state_after_resume = await workflow.run(resumed_state)

    print(f"  ✓ Workflow resumed successfully")
    print(f"  ✓ New state: {state_after_resume['current_state']}")
    assert state_after_resume['current_state'] == 'phenotype_review'

    # ===== Step 5: Verify No Data Loss =====
    print("\\n[5/5] Verifying data integrity after resumption...")

    assert state_after_resume.get('requirements') is not None
    assert state_after_resume.get('requirements_complete') == True
    assert state_after_resume['request_id'] == request_id

    print("  ✓ All data preserved after resumption")
    print("  ✓ No data loss detected")

    elapsed_time = time.time() - start_time

    print("\\n" + "=" * 80)
    print("✅ STATE PERSISTENCE TEST PASSED")
    print("=" * 80)
    print(f"Request ID: {request_id}")
    print(f"Checkpoint: requirements_review")
    print(f"Resumed: Successfully from PostgreSQL")
    print(f"Execution Time: {elapsed_time:.2f} seconds")
    print("✓ State persistence working correctly")
    print("✓ Workflow resumption working correctly")
    print("✓ No data loss after load")
    print("=" * 80)


# ============================================================================
# Test Runner
# ============================================================================

if __name__ == "__main__":
    """
    Run LangGraph E2E tests manually

    Prerequisites:
    1. Start Docker PostgreSQL:
       docker-compose -f config/docker-compose.yml up -d db

    2. Initialize database schema:
       python scripts/init_test_db.py

    3. Set environment variable:
       export ANTHROPIC_API_KEY=sk-ant-api03-...

    4. Run tests:
       pytest tests/e2e/test_langgraph_workflow_e2e.py -v -s
    """
    pytest.main([__file__, "-v", "-s", "-m", "e2e"])
