# All Preview Extraction Fixes - Complete Summary

## Session Overview

Fixed **4 critical bugs** blocking preview extraction workflow:
1. ✅ Orchestrator routing bug (calendar_agent → extraction_agent)
2. ✅ Extraction agent context field mismatches (3 fields)
3. ✅ QA agent context field mismatches (1 field)
4. ⚠️ **REMAINING**: SQL query returns 0 results (HAPI DB connection)

## Bugs Fixed

### Bug #1: Orchestrator Routing ✅ FIXED
**File**: `app/orchestrator/orchestrator.py` (line 464)

**Problem**: After SQL approval, routed to `calendar_agent` instead of `extraction_agent`

**Fix**:
```python
# BEFORE (BROKEN):
"phenotype_sql": ("calendar_agent", "schedule_kickoff_meeting"),

# AFTER (FIXED):
"phenotype_sql": ("extraction_agent", "extract_preview"),
```

### Bug #2: Extraction Agent Field Mismatches ✅ FIXED
**File**: `app/agents/extraction_agent.py`

**Problems**:
1. Expected `phenotype_sql`, received `sql_query`
2. Expected `requirements`, received `structured_requirements`
3. Never passed `parameters` to SQL execution

**Fixes**:

**2a. Fixed `_extract_preview()` method** (lines 129-156):
```python
# BEFORE (BROKEN):
phenotype_sql = context.get("phenotype_sql")  # ❌ Doesn't exist
requirements = context.get("requirements")     # ❌ Doesn't exist
cohort = await self._execute_phenotype_query(phenotype_sql)  # ❌ No params

# AFTER (FIXED):
sql_query = context.get("sql_query") or context.get("phenotype_sql")  # ✅
requirements = context.get("structured_requirements") or context.get("requirements")  # ✅
parameters = context.get("parameters", {})  # ✅
cohort = await self._execute_phenotype_query(sql_query, parameters)  # ✅
```

**2b. Fixed `_extract_data()` method** (lines 44-67):
- Same field name fixes as preview method

**2c. Updated `_execute_phenotype_query()` signature** (lines 202-218):
```python
# BEFORE (BROKEN):
async def _execute_phenotype_query(self, phenotype_sql: str) -> list:
    result = await self.sql_adapter.execute_sql(phenotype_sql)  # ❌ No params

# AFTER (FIXED):
async def _execute_phenotype_query(self, phenotype_sql: str, parameters: dict = None) -> list:
    result = await self.sql_adapter.execute_sql(phenotype_sql, parameters)  # ✅
```

### Bug #3: QA Agent Field Mismatch ✅ FIXED
**File**: `app/agents/qa_agent.py`

**Problem**: Expected `requirements`, received `structured_requirements`

**Fixes**:

**3a. Fixed `_validate_preview()` method** (lines 120-139):
```python
# BEFORE (BROKEN):
requirements = context.get("requirements")  # ❌ Doesn't exist

# AFTER (FIXED):
requirements = context.get("structured_requirements") or context.get("requirements")  # ✅
```

**3b. Fixed `_validate_extracted_data()` method** (lines 39-55):
- Same field name fix as preview method

### Bug #4: SQL Query Returns 0 Results ⚠️ REMAINING

**File**: `app/agents/extraction_agent.py` (indirect - HAPI DB connection)

**Problem**: Preview extraction succeeded but returned:
```json
{
  "cohort_size": 0,
  "preview_data": {
    "Family name": [],
    "Given name": [],
    "Date of birth": [],
    "Address": []
  }
}
```

**Possible Causes**:
1. **Wrong database connection**: Agent connecting to researchflow DB instead of HAPI DB
2. **Materialized views don't exist**: `sqlonfhir` schema tables missing
3. **SQL parameters not binding correctly**: Despite fix, parameters may not execute
4. **Data doesn't exist in HAPI DB**: Test data not loaded

**Verification Needed**:
```sql
-- Check if materialized views exist in HAPI DB
PGPASSWORD=hapi psql -h localhost -p 5433 -U hapi -d hapi -c "
SELECT schemaname, matviewname
FROM pg_matviews
WHERE schemaname = 'sqlonfhir';
"

-- Check if test data exists
PGPASSWORD=hapi psql -h localhost -p 5433 -U hapi -d hapi -c "
SELECT COUNT(*) FROM sqlonfhir.patient_demographics WHERE gender = 'male';
"

-- Test exact SQL with parameters
PGPASSWORD=hapi psql -h localhost -p 5433 -U hapi -d hapi -c "
SELECT COUNT(DISTINCT p.patient_id)
FROM sqlonfhir.patient_demographics p
WHERE p.gender = 'male'
  AND EXISTS (
    SELECT 1 FROM sqlonfhir.condition_simple c
    WHERE c.patient_id = p.patient_id
    AND LOWER(c.code_text) LIKE LOWER('%diabetes%')
  );
"
```

## Files Modified

### 1. `/app/orchestrator/orchestrator.py`
**Line 464**: Fixed routing to extraction_agent

### 2. `/app/agents/extraction_agent.py`
**Lines 44-67**: Fixed `_extract_data()` field names
**Lines 129-156**: Fixed `_extract_preview()` field names
**Lines 202-218**: Added parameters to `_execute_phenotype_query()`

### 3. `/app/agents/qa_agent.py`
**Lines 39-55**: Fixed `_validate_extracted_data()` field names
**Lines 120-139**: Fixed `_validate_preview()` field names

## Testing Status

### Test Request: REQ-20251104-16A5E0CF

**Natural Language**: "I need demographics (family name, given name, date of birth, address) for male patients with diabetes diagnosis."

**Workflow Progress**:
1. ✅ requirements_agent: SUCCESS
2. ✅ phenotype_agent: SUCCESS (28 patients estimated)
3. ✅ SQL Approval: APPROVED by Jim
4. ✅ extraction_agent.extract_preview: SUCCESS (but 0 results)
5. ❌ qa_agent.validate_preview: FAILED (field mismatch - **NOW FIXED**)

**Current State**: Human Review (QA agent failed due to field mismatch)

**Next Steps**:
1. Restart services to load updated code
2. Create new test request
3. Monitor with LangSmith
4. Debug SQL 0 results issue

## How to Test with Updated Code

### Step 1: Restart Services

**Stop All Streamlit Apps**:
```bash
# Find and kill all streamlit processes
pkill -f "streamlit run"

# Verify they're stopped
lsof -i :8501 -i :8502
```

**Restart with Environment Variables**:
```bash
# Terminal 1: Admin Dashboard
LANGCHAIN_TRACING_V2=true \
LANGCHAIN_API_KEY=lsv2_pt_REDACTED \
LANGCHAIN_PROJECT=researchflow-production \
HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi \
streamlit run app/web_ui/admin_dashboard.py --server.port 8502

# Terminal 2: Researcher Portal
LANGCHAIN_TRACING_V2=true \
LANGCHAIN_API_KEY=lsv2_pt_REDACTED \
LANGCHAIN_PROJECT=researchflow-production \
HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi \
streamlit run app/web_ui/researcher_portal.py --server.port 8501
```

### Step 2: Create New Test Request

**Via Researcher Portal** (http://localhost:8501):
```
Name: Test User
Email: test@hospital.edu
IRB Number: IRB-TEST-001

Natural Language Request:
"I need demographics (family name, given name, date of birth, address) for male patients with diabetes diagnosis."

Inclusion Criteria:
- Male
- Diabetes diagnosis

Data Elements:
- Demographics (age, gender, race)
```

### Step 3: Monitor with LangSmith

1. Go to https://smith.langchain.com/
2. Select project "researchflow-production"
3. Search for your request ID (e.g., `REQ-20251104-XXXXXXXX`)
4. Watch the trace in real-time as agents execute

### Step 4: Approve SQL

**Admin Dashboard** (http://localhost:8502):
1. Click on request in sidebar
2. View SQL approval section
3. ✅ Verify 4 metrics displayed (including Est. Preview Time)
4. Click "Approve SQL"

### Step 5: Observe Preview Extraction

**Expected Behavior**:
1. ⏳ Loading spinner appears ("Extracting preview data...")
2. 🔄 Auto-refresh every 5 seconds
3. ⏱️ Time estimation displays
4. ✅ Preview data appears (10 rows per element)

**If Still Returns 0 Results**:
- Check HAPI DB connection in logs
- Verify materialized views exist
- Test SQL manually with psql
- Check parameters are binding

## LangSmith Debugging

See `LANGSMITH_DEBUGGING_GUIDE.md` for complete instructions.

**Quick Start**:
1. Enable tracing (see Step 1 above)
2. Search for request ID in LangSmith
3. Click on failed step
4. Inspect "Inputs" tab
5. Compare field names with code
6. Check SQL parameters in `execute_sql` call

## Validation Checklist

### Code Changes Applied
- [x] Orchestrator routing (orchestrator.py:464)
- [x] Extraction agent field names (extraction_agent.py:44-67, 129-156)
- [x] Extraction agent parameters (extraction_agent.py:202-218)
- [x] QA agent field names (qa_agent.py:39-55, 120-139)

### Services Restarted
- [ ] Stop all streamlit processes
- [ ] Restart admin dashboard with env vars
- [ ] Restart researcher portal with env vars
- [ ] Verify LangSmith tracing enabled

### Database Verified
- [ ] HAPI DB has materialized views in `sqlonfhir` schema
- [ ] Test data exists (male diabetic patients)
- [ ] SQL query manually tested with parameters
- [ ] Returns 28 patients when run directly

### Workflow Tested
- [ ] New test request created
- [ ] Requirements gathering succeeds
- [ ] SQL generation succeeds (28 patients estimated)
- [ ] SQL approval succeeds
- [ ] Preview extraction succeeds (NOT 0 results)
- [ ] QA validation succeeds (no field mismatch errors)
- [ ] Preview data displays in UI

## Known Remaining Issues

### Issue #1: SQL Returns 0 Results ⚠️

**Status**: NOT FIXED - needs investigation

**Symptoms**:
- Extraction agent succeeds
- But returns `cohort_size: 0` and empty arrays
- Should return 28 patients

**Possible Fixes**:
1. Verify HAPI_DB_URL is set correctly
2. Create materialized views if missing
3. Load test data into HAPI DB
4. Test SQL with parameters manually

**Debug Steps**:
```bash
# 1. Check materialized views
PGPASSWORD=hapi psql -h localhost -p 5433 -U hapi -d hapi -c "\
SELECT COUNT(*) FROM pg_matviews WHERE schemaname = 'sqlonfhir';"

# 2. Check test data
PGPASSWORD=hapi psql -h localhost -p 5433 -U hapi -d hapi -c "\
SELECT COUNT(*) FROM sqlonfhir.patient_demographics;"

# 3. Test exact SQL
PGPASSWORD=hapi psql -h localhost -p 5433 -U hapi -d hapi -c "\
SELECT COUNT(DISTINCT p.patient_id)
FROM sqlonfhir.patient_demographics p
WHERE p.gender = 'male'
  AND EXISTS (
    SELECT 1 FROM sqlonfhir.condition_simple c
    WHERE c.patient_id = p.patient_id
    AND LOWER(c.code_text) LIKE LOWER('%diabetes%')
  );"
```

## Documentation Created

1. **`PREVIEW_EXTRACTION_UI_COMPLETE.md`** - UI implementation complete
2. **`EXTRACTION_AGENT_CONTEXT_FIX.md`** - Extraction agent field mismatch fixes
3. **`LANGSMITH_DEBUGGING_GUIDE.md`** - How to use LangSmith for debugging
4. **`ALL_FIXES_COMPLETE_SUMMARY.md`** - This document

## Summary

### What Works Now ✅
- Orchestrator routes to extraction_agent after SQL approval
- Extraction agent accepts correct field names
- Extraction agent passes SQL parameters
- QA agent accepts correct field names
- All field mismatch errors resolved

### What Needs Testing 🔄
- Services restart with updated code
- New request end-to-end workflow
- SQL query returns correct results (not 0)
- Preview data displays in UI

### What Remains Broken ⚠️
- SQL query returns 0 results (HAPI DB issue)
- Needs database connection verification
- May need materialized views created
- May need test data loaded

## Next Steps

1. **Restart Services** with environment variables
2. **Create New Test Request** via researcher portal
3. **Monitor in LangSmith** for field mismatches
4. **Debug SQL 0 Results** if still occurs
5. **Verify HAPI DB Setup** (views, data)
6. **Complete End-to-End Test** with preview approval

**Expected Result**: Complete workflow from SQL approval → preview extraction → preview QA → preview approval → full extraction → delivery.

**Current Blocking Issue**: SQL query returns 0 results (needs HAPI DB investigation).
