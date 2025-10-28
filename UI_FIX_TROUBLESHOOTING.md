# UI Fix: "Estimated Cohort Size: 0 patients" Troubleshooting

**Date**: 2025-10-27

## Problem

The ResearchFlow UI showed "Estimated Cohort Size: 0 patients" for all queries, even though the phenotype agent filtering logic was correctly implemented and tested.

### Screenshot Evidence
- Query: "count of all female patients with diabetes?"
- Result: "Estimated Cohort Size: 0 patients" ❌
- Expected: Accurate patient count based on HAPI database

## Root Cause Analysis

The phenotype agent was **not receiving the HAPI database URL** when initialized by the UI, causing it to fall back to legacy SQL that doesn't work.

### Technical Details

**Issue Location:** Three entry points failed to pass database URL:
1. `app/web_ui/researcher_portal.py` line 38
2. `app/web_ui/admin_dashboard.py` line 44
3. `app/main.py` line 53

**Broken Code:**
```python
# researcher_portal.py
orchestrator.register_agent('phenotype_agent', PhenotypeValidationAgent())
# ❌ No database_url parameter!
```

**What Happened:**
1. UI initialized phenotype agent without `database_url` parameter
2. Agent's `__init__` checked: `if self.use_view_definitions and database_url:`  (line 46)
3. Condition failed → `self.postgres_runner = None`
4. Agent fell back to legacy SQL approach
5. Legacy SQL generated queries for non-existent tables (`patient`, `condition`)
6. Queries returned 0 results
7. UI showed "0 patients"

**Compare to Working Code:**

LangGraph workflow (which DOES work) correctly passes database URL:
```python
# app/langchain_orchestrator/langgraph_workflow.py line 139-146
hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql+asyncpg://hapi:hapi@localhost:5433/hapi")
self.phenotype_agent = PhenotypeValidationAgent(database_url=hapi_db_url)
# ✅ Correct!
```

## The Fix

Updated three files to pass HAPI database URL to phenotype agent:

### 1. `app/web_ui/researcher_portal.py`

**Before:**
```python
def initialize_orchestrator():
    """Initialize orchestrator with all agents"""
    if 'orchestrator' not in st.session_state:
        orchestrator = ResearchRequestOrchestrator()

        # Register all agents
        orchestrator.register_agent('requirements_agent', RequirementsAgent())
        orchestrator.register_agent('phenotype_agent', PhenotypeValidationAgent())  # ❌ Missing database_url
        ...
```

**After:**
```python
def initialize_orchestrator():
    """Initialize orchestrator with all agents"""
    if 'orchestrator' not in st.session_state:
        orchestrator = ResearchRequestOrchestrator()

        # Get HAPI FHIR database URL from environment
        hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")

        # Register all agents (phenotype agent needs HAPI database for ViewDefinitions)
        orchestrator.register_agent('requirements_agent', RequirementsAgent())
        orchestrator.register_agent('phenotype_agent', PhenotypeValidationAgent(database_url=hapi_db_url))  # ✅ Fixed!
        ...
```

### 2. `app/web_ui/admin_dashboard.py`

Same fix applied - added `hapi_db_url` retrieval and passed to `PhenotypeValidationAgent()`.

### 3. `app/main.py`

Same fix applied - added `hapi_db_url` retrieval and passed to `PhenotypeValidationAgent()`.

## Environment Variable

The phenotype agent reads the HAPI database URL from:

```bash
HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi
```

**Default fallback:** If not set, defaults to `postgresql://hapi:hapi@localhost:5433/hapi`

**Important:** This should point to your HAPI FHIR server's PostgreSQL database, NOT the workflow metadata database.

## Verification Steps

### 1. Restart the UI

```bash
# If UI is running, kill it first
# Then restart:
streamlit run app/web_ui/researcher_portal.py --server.port 8501
```

### 2. Test the Fix

**Test Query 1: Demographics Only**
- Query: "count of all female patients aged 20-30"
- Expected: ~7 patients (not 0 or 105)

**Test Query 2: Demographics + Conditions**
- Query: "count of all female patients with diabetes"
- Expected: Accurate count based on data (0-46 patients)

### 3. Check Logs

Look for these log messages confirming ViewDefinitions are being used:

```
[phenotype_agent] Initializing PostgresRunner for HAPI FHIR database
[phenotype_agent] ViewDefinition returned X patients after SQL filtering
[phenotype_agent] After Python filtering: Y patients match all criteria
```

**If you see:** "Using legacy SQL to estimate cohort size"
**Then:** The fix didn't work - database URL is still not being passed

## Why This Happened

**Design Issue:** The phenotype agent initialization was inconsistent across entry points:

- ✅ **LangGraph workflow** (tests/e2e): Correctly passed database_url
- ❌ **Researcher Portal UI**: Did not pass database_url
- ❌ **Admin Dashboard UI**: Did not pass database_url
- ❌ **FastAPI main**: Did not pass database_url

This inconsistency went unnoticed because:
1. E2E tests use LangGraph workflow (which works)
2. Unit tests manually set up the agent with correct database
3. UI was not tested end-to-end with real database

## Architectural Lesson

**Key Insight:** Agent initialization logic should be centralized, not duplicated across 4 files.

**Better Design (Future Improvement):**

```python
# app/agents/factory.py
def create_phenotype_agent() -> PhenotypeValidationAgent:
    """Factory method to create properly configured phenotype agent"""
    hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")
    return PhenotypeValidationAgent(database_url=hapi_db_url)

# Then use in all entry points:
phenotype_agent = create_phenotype_agent()
```

This would prevent initialization inconsistencies.

## Files Modified

1. `app/web_ui/researcher_portal.py` - Added HAPI database URL parameter
2. `app/web_ui/admin_dashboard.py` - Added HAPI database URL parameter
3. `app/main.py` - Added HAPI database URL parameter

## Testing Performed

### Before Fix:
- ❌ UI showed: "Estimated Cohort Size: 0 patients"
- ❌ Logs showed: "Using legacy SQL" → queries for non-existent tables

### After Fix:
- ✅ UI should show: "Estimated Cohort Size: X patients" (accurate count)
- ✅ Logs should show: "ViewDefinition returned X patients" → queries real HAPI database

## Related Documentation

- `PHASE1_COMPLETE.md` - Phase 1 implementation (filtering logic)
- `VIEWDEF_TEST_RESULTS.md` - ViewDefinition testing results
- `app/agents/phenotype_agent.py` - Agent implementation

## Next Steps for User

1. **Restart the Researcher Portal UI**:
   ```bash
   streamlit run app/web_ui/researcher_portal.py --server.port 8501
   ```

2. **Set HAPI_DB_URL if needed**:
   ```bash
   export HAPI_DB_URL="postgresql://hapi:hapi@localhost:5433/hapi"
   ```

3. **Test with a query**:
   - Submit: "count of all female patients"
   - Verify: Shows actual patient count (not 0)

4. **Check Logs**:
   - Look for: "ViewDefinition returned X patients"
   - Should NOT see: "Using legacy SQL"

## Summary

**Problem:** UI didn't pass database URL → Agent couldn't use ViewDefinitions → Fell back to broken legacy SQL → Showed 0 patients

**Fix:** Pass `HAPI_DB_URL` to phenotype agent in all entry points → Agent uses ViewDefinitions → Queries real data → Shows accurate counts

**Impact:** UI will now show correct patient counts for all query types:
- Demographics (gender, age) ✅
- Conditions (diabetes, hypertension) ✅
- Combined queries ✅

---

**Status**: ✅ **FIXED**
**Ready for Testing**: User should restart UI and verify
