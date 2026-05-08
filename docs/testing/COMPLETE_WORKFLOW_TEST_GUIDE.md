# Complete Workflow Validation Guide

## Test Request Details
**Data Request**: "I need demographics (family name, given name, date of birth, address) for male patients with diabetes diagnosis"

**Expected Cohort**: 28 male patients with diabetes (verified in HAPI DB)

## Phase 1: Submit Request (Researcher Portal)

### Steps:
1. Open browser and navigate to: **http://localhost:8501**
2. Fill in the form:
   - **Name**: Test User
   - **Email**: test@hospital.edu
   - **IRB Protocol**: IRB-TEST-001
   - **Data Request**: "I need demographics (family name, given name, date of birth, address) for male patients with diabetes diagnosis"
3. Click **Submit Request**

### Verification Points:
- ✅ Request appears in left sidebar with status "Gathering requirements..."
- ✅ After 2-3 seconds, status changes to "Requirements Review" or "Feasibility Validation"
- ✅ SQL query is generated (you should see phenotype_review state)
- ✅ Request ID is displayed (note this down: `REQ-XXXXXXXX`)

### Database Check:
```bash
# Check request was created
HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

async def check():
    engine = create_async_engine('sqlite+aiosqlite:///./dev.db')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await session.execute(text('SELECT request_id, workflow_state, created_at FROM research_request ORDER BY created_at DESC LIMIT 1'))
        row = result.fetchone()
        if row:
            print(f'Latest Request: {row[0]}')
            print(f'State: {row[1]}')
            print(f'Created: {row[2]}')
        else:
            print('No requests found')

asyncio.run(check())
"
```

---

## Phase 2: Approve SQL (Admin Dashboard)

### Steps:
1. Open new browser tab: **http://localhost:8502**
2. Find your request in the "Pending Approvals" section
3. Review the generated SQL query (should query patient_demographics and condition_simple)
4. Click **Approve SQL**

### Verification Points:
- ✅ No "logger not defined" errors (Bug #2 fix)
- ✅ Success message: "SQL approved successfully"
- ✅ Request disappears from pending approvals
- ✅ State transitions to "preview_extraction"

### Database Check:
```bash
# Check approval was recorded and state changed
python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

async def check():
    engine = create_async_engine('sqlite+aiosqlite:///./dev.db')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        # Get latest request
        result = await session.execute(text('SELECT request_id, workflow_state FROM research_request ORDER BY created_at DESC LIMIT 1'))
        req = result.fetchone()
        print(f'Request {req[0]} - State: {req[1]}')

        # Check for approval
        result = await session.execute(text('SELECT approval_type, status FROM approval WHERE request_id = :rid'), {'rid': req[0]})
        approvals = result.fetchall()
        print(f'Approvals: {approvals}')

asyncio.run(check())
"
```

---

## Phase 3: Monitor Preview Extraction

### Steps:
1. Return to **Researcher Portal** (http://localhost:8501)
2. Click on your request in the sidebar
3. Watch the status updates (auto-refreshes every 5 seconds)

### Verification Points:
- ✅ Status shows "Extracting preview data..."
- ✅ Preview extraction completes within 10-20 seconds
- ✅ Preview data table appears with 10 patients
- ✅ **CRITICAL**: Family name, Given name, DOB, Address columns are populated (not empty!)
- ✅ All patients are male with diabetes diagnosis

### Database Check:
```bash
# Check extraction agent execution
python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

async def check():
    engine = create_async_engine('sqlite+aiosqlite:///./dev.db')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        # Get latest extraction execution
        result = await session.execute(text('''
            SELECT agent_id, task, status, error_message
            FROM agent_execution
            WHERE agent_id = 'extraction_agent'
            ORDER BY started_at DESC LIMIT 1
        '''))
        row = result.fetchone()
        if row:
            print(f'Agent: {row[0]}, Task: {row[1]}, Status: {row[2]}')
            if row[3]:
                print(f'Error: {row[3]}')
        else:
            print('No extraction executions found')

asyncio.run(check())
"
```

### Log Check:
```bash
# Check for errors in extraction agent
tail -20 /tmp/researcher_portal.log | grep -i "error\|exception\|traceback"
```

---

## Phase 4: Handle Preview QA (If Needed)

### Expected Behavior:
Preview QA will likely **FAIL** due to cohort mismatch:
- **Actual**: 10 patients (preview sample)
- **Estimated**: 28 patients
- **Tolerance**: ±10% (2.8 patients)
- **Mismatch**: 18 patients difference (> tolerance)

### Steps:
1. Return to **Admin Dashboard** (http://localhost:8502)
2. Check "Pending Approvals" for "Preview QA Review"
3. Review the QA report showing cohort mismatch
4. Click **Approve** to proceed to full extraction

### Verification Points:
- ✅ Preview QA approval UI is displayed (Bug #11 fix)
- ✅ QA report shows cohort mismatch details
- ✅ Approval button works without errors
- ✅ After approval, state transitions to "data_extraction"

### Database Check:
```bash
# Check preview QA approval
python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

async def check():
    engine = create_async_engine('sqlite+aiosqlite:///./dev.db')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await session.execute(text('''
            SELECT approval_type, status, created_at
            FROM approval
            WHERE approval_type = 'preview_qa'
            ORDER BY created_at DESC LIMIT 1
        '''))
        row = result.fetchone()
        if row:
            print(f'Preview QA Approval: {row[0]} - Status: {row[1]} - Created: {row[2]}')
        else:
            print('No preview QA approval found')

asyncio.run(check())
"
```

---

## Phase 5: Monitor Full Data Extraction

### Steps:
1. Return to **Researcher Portal** (http://localhost:8501)
2. Click on your request in the sidebar
3. Watch the status updates

### Verification Points:
- ✅ Status shows "Extracting data..." (Bug #12 fix - context enrichment)
- ✅ **NO NoneType errors** in logs (Bug #12 fix - defensive null checks)
- ✅ Full extraction completes within 30-60 seconds
- ✅ Dataset shows all 28 male diabetic patients
- ✅ All demographic fields populated (family name, given name, DOB, address)

### Database Check:
```bash
# Check full extraction execution
python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

async def check():
    engine = create_async_engine('sqlite+aiosqlite:///./dev.db')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        # Get latest extraction execution for extract_data task
        result = await session.execute(text('''
            SELECT agent_id, task, status, error_message, started_at, completed_at
            FROM agent_execution
            WHERE agent_id = 'extraction_agent' AND task = 'extract_data'
            ORDER BY started_at DESC LIMIT 1
        '''))
        row = result.fetchone()
        if row:
            print(f'Agent: {row[0]}, Task: {row[1]}, Status: {row[2]}')
            print(f'Started: {row[4]}, Completed: {row[5]}')
            if row[3]:
                print(f'ERROR: {row[3]}')
        else:
            print('No full extraction executions found')

asyncio.run(check())
"
```

### Log Check:
```bash
# Check for NoneType errors (should be ZERO)
tail -50 /tmp/researcher_portal.log | grep -i "NoneType\|'NoneType' object"
```

---

## Phase 6: QA Validation & Delivery

### Steps:
1. Wait for QA validation to complete automatically
2. Return to **Admin Dashboard** (http://localhost:8502)
3. Find "Delivery Review" approval for your request
4. Review the QA report (should show "passed")
5. Click **Approve Delivery**

### Verification Points:
- ✅ QA validation completes successfully
- ✅ QA report shows:
  - Completeness check: passed
  - Duplicate check: passed
  - PHI scrubbing: passed
  - Overall status: passed
- ✅ Delivery approval works without errors
- ✅ State transitions to "delivered"

### Database Check:
```bash
# Check QA and delivery status
python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

async def check():
    engine = create_async_engine('sqlite+aiosqlite:///./dev.db')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        # Get latest request
        result = await session.execute(text('SELECT request_id, workflow_state FROM research_request ORDER BY created_at DESC LIMIT 1'))
        req = result.fetchone()
        print(f'Request: {req[0]} - State: {req[1]}')

        # Check QA execution
        result = await session.execute(text('''
            SELECT agent_id, task, status
            FROM agent_execution
            WHERE agent_id = 'qa_agent' AND task = 'validate_extracted_data'
            ORDER BY started_at DESC LIMIT 1
        '''))
        qa_row = result.fetchone()
        if qa_row:
            print(f'QA Agent: {qa_row[2]}')

        # Check delivery execution
        result = await session.execute(text('''
            SELECT agent_id, task, status
            FROM agent_execution
            WHERE agent_id = 'delivery_agent'
            ORDER BY started_at DESC LIMIT 1
        '''))
        del_row = result.fetchone()
        if del_row:
            print(f'Delivery Agent: {del_row[2]}')

asyncio.run(check())
"
```

---

## Phase 7: Verify Data Download

### Steps:
1. Return to **Researcher Portal** (http://localhost:8501)
2. Click on your request in the sidebar
3. Scroll down to "Delivered Data" section
4. Click **Download Dataset** button

### Verification Points:
- ✅ Download button is visible and enabled
- ✅ CSV file downloads successfully (filename: `{request_id}_dataset.csv`)
- ✅ CSV contains all 28 male diabetic patients
- ✅ CSV has columns: patient_id, family_name, given_name, date_of_birth, address
- ✅ All fields are populated (no null/empty values for existing data)

### CSV Validation:
```bash
# Check downloaded CSV
head -20 ~/Downloads/*_dataset.csv
```

---

## Success Criteria Summary

All 12 bug fixes validated:

| Bug # | Description | Validation |
|-------|-------------|------------|
| #1 | Orchestrator routing after SQL approval | ✅ Preview extraction starts automatically |
| #2 | Logger not defined error | ✅ No errors when clicking approve |
| #3 | Database column mismatch (race/address) | ✅ No SQL errors in logs |
| #4 | Preview QA failure workflow gap | ✅ Workflow rule routes to HUMAN_REVIEW |
| #5 | Orchestrator next_agent_map missing qa_agent | ✅ QA agent executes after extraction |
| #6 | Missing demographics extraction | ✅ Preview data shows family name, given name, DOB, address |
| #7 | Field name mismatch (gender vs sex) | ✅ Gender field populated correctly |
| #8 | SQL column not exists (race) | ✅ No race column errors |
| #9 | SQL column not exists (address) | ✅ No address column errors (returns empty if unavailable) |
| #10 | Referential integrity (request_id) | ✅ All database queries use correct request_id |
| #11 | Preview QA approval workflow | ✅ Preview QA approval UI displayed and functional |
| #12 | Extraction context enrichment | ✅ No NoneType errors, extraction completes successfully |

---

## Troubleshooting

### If request gets stuck:
1. Check logs:
   ```bash
   tail -50 /tmp/researcher_portal.log
   tail -50 /tmp/admin_dashboard.log
   ```

2. Check database state:
   ```bash
   python -c "
   import asyncio
   from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
   from sqlalchemy import select, text
   from sqlalchemy.orm import sessionmaker

   async def check():
       engine = create_async_engine('sqlite+aiosqlite:///./dev.db')
       async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
       async with async_session() as session:
           result = await session.execute(text('''
               SELECT request_id, workflow_state, current_agent, current_task
               FROM research_request
               ORDER BY created_at DESC LIMIT 1
           '''))
           row = result.fetchone()
           if row:
               print(f'Request: {row[0]}')
               print(f'State: {row[1]}')
               print(f'Current Agent: {row[2]}')
               print(f'Current Task: {row[3]}')

   asyncio.run(check())
   "
   ```

3. Check for pending approvals:
   ```bash
   python -c "
   import asyncio
   from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
   from sqlalchemy import select, text
   from sqlalchemy.orm import sessionmaker

   async def check():
       engine = create_async_engine('sqlite+aiosqlite:///./dev.db')
       async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
       async with async_session() as session:
           result = await session.execute(text('''
               SELECT approval_type, status, created_at
               FROM approval
               WHERE status = 'pending'
               ORDER BY created_at DESC
           '''))
           rows = result.fetchall()
           if rows:
               for row in rows:
                   print(f'{row[0]}: {row[1]} (created {row[2]})')
           else:
               print('No pending approvals')

   asyncio.run(check())
   "
   ```

### If logs show errors:
- Search for "ERROR", "Exception", "Traceback" in logs
- Check agent_execution table for error_message field
- Verify HAPI database is accessible: `PGPASSWORD=hapi psql -h localhost -p 5433 -U hapi -d hapi -c "SELECT COUNT(*) FROM patient;"`

---

## LangSmith Monitoring

Monitor the complete workflow in LangSmith:
- URL: https://smith.langchain.com/projects/researchflow-production
- Look for traces showing:
  - Requirements agent execution
  - Phenotype agent execution (SQL generation)
  - Extraction agent execution (preview + full)
  - QA agent execution (preview QA + full QA)
  - Delivery agent execution

---

## Expected Timeline

- Request submission: < 5 seconds
- SQL generation: 2-3 seconds
- Preview extraction: 10-20 seconds
- Preview QA: 5-10 seconds
- Full extraction: 30-60 seconds
- Full QA: 10-20 seconds
- Delivery: 5-10 seconds

**Total workflow time**: 2-4 minutes (excluding human approval time)
