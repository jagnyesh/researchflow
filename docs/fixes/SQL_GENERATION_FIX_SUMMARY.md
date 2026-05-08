# SQL Generation Fix Summary

## Problem Statement
SQL generation for male diabetic patients was producing **0 estimated cohort** instead of the expected **28 patients**.

## Root Causes Identified

### 1. ✅ **FIXED: Type Mismatch Bug**
**Location**: `app/utils/sql_generator.py:191`

**Issue**: Code checked for `concept_type == "demographic"` (singular) but LLM returns `"demographics"` (plural), causing gender filters to be silently dropped.

**Fix**: Changed line 191 from:
```python
elif concept_type == "demographic":
```
To:
```python
elif concept_type == "demographics":
```

### 2. ✅ **FIXED: Column Name Mismatches**
**Location**: `app/utils/sql_generator.py:93-108`

**Issue**: Hardcoded field mappings used wrong column names that don't exist in the actual database schema.

**Actual Schema** (`sqlonfhir.patient_demographics`):
- `name_family` (not `family_name`)
- `name_given` (not `given_name`)
- `dob` (not `birth_date` or `birthdate`)
- **No address fields** (address_line, city, state, postal_code don't exist)

**Fix**: Updated field_mapping dictionary:
```python
field_mapping = {
    "demographics": ["name_family", "name_given", "dob", "gender"],
    "family name": ["name_family"],
    "given name": ["name_given"],
    "date of birth": ["dob"],
    "dob": ["dob"],
    "gender": ["gender"],
    "address": [],  # Not available in materialized views
}
```

### 3. ✅ **FIXED: Dynamic SELECT Clause**
**Location**: `app/utils/sql_generator.py:79-175`

**Issue**: SELECT clause was hardcoded, ignoring user's requested `data_elements`.

**Fix**: Added `_build_select_fields()` method that:
- Maps data elements to actual database columns
- Gracefully handles unavailable fields (logs warnings, continues with available fields)
- Returns dynamic SELECT list based on requirements

## Test Results

### Before Fixes
```sql
-- Generated SQL (BROKEN):
SELECT DISTINCT
    p.patient_id as patient_id,
    p.family_name,      ❌ Column doesn't exist
    p.given_name,       ❌ Column doesn't exist
    p.birth_date,       ❌ Column doesn't exist
    p.address_line,     ❌ Column doesn't exist
    ...
FROM sqlonfhir.patient_demographics p
-- Missing WHERE p.gender filter!  ❌
```
**Result**: 0 patients (SQL would fail if executed)

### After Fixes
```sql
-- Generated SQL (CORRECT):
SELECT DISTINCT
    p.patient_id as patient_id,
    p.name_family,      ✅ Correct column
    p.name_given,       ✅ Correct column
    p.dob               ✅ Correct column
FROM sqlonfhir.patient_demographics p
WHERE p.gender = :gender_1 AND EXISTS (  ✅ Gender filter present!
    SELECT 1 FROM sqlonfhir.condition_simple c
    WHERE c.patient_id = p.patient_id
    AND LOWER(c.code_text) LIKE LOWER(:condition_2)
)
```
**Result**: 28 patients ✅

### Direct SQL Execution Test
```bash
$ psql -c "SELECT COUNT(...) FROM sqlonfhir.patient_demographics p WHERE p.gender = 'male' AND ..."
 patient_count
---------------
            28
```
**✅ SQL executes correctly and returns 28 patients**

## Files Modified

1. **`app/utils/sql_generator.py`**
   - Line 191: Fixed type mismatch (`demographic` → `demographics`)
   - Lines 93-108: Updated field_mapping with correct column names
   - Lines 79-141: Added `_build_select_fields()` method
   - Lines 114-118: Updated default demographics columns
   - Lines 173-175: Updated generate_phenotype_sql() to use dynamic SELECT

2. **`scripts/test_sql_generation.py`**
   - Updated test data to use `"type": "demographics"` (plural)

## Verification Steps

### Test Case
**Natural Language**: "I need demographics (family name, given name, date of birth, address) for male patients with diabetes diagnosis."

**Inclusion Criteria**:
- Male
- Diabetes Diagnosis

**Expected Behavior**:
1. ✅ LLM extracts concepts with type "demographics" (plural)
2. ✅ SQL Generator recognizes "demographics" type
3. ✅ Gender filter is added: `WHERE p.gender = 'male'`
4. ✅ Column names match actual schema: `name_family`, `name_given`, `dob`
5. ✅ Address fields are skipped with warning (not in schema)
6. ✅ SQL returns 28 male diabetic patients

### Test Execution
**Request IDs**:
- `REQ-20251104-E4F22949` - Before fix (0 patients, wrong columns)
- `REQ-20251104-8B409324` - After fix (correct SQL, address gracefully skipped)

**SQL Verification**:
```bash
# Direct execution
PGPASSWORD=hapi psql -h localhost -p 5433 -U hapi -d hapi -c "SELECT COUNT(DISTINCT p.patient_id)..."
Result: 28 patients ✅
```

## Remaining Issue ⚠️

**Problem**: Phenotype Agent's COUNT query execution still returns **estimated_cohort: 0** instead of 28.

**Status**: SQL generation is now **100% correct**, but there's a separate bug in how the parameterized query is being executed during feasibility checks.

**Next Steps**:
1. Investigate `app/adapters/sql_on_fhir.py` - how `execute_sql()` handles parameters
2. Check if parameter binding is working correctly (`:gender_1`, `:condition_2`)
3. Review PhenotypeValidationAgent's COUNT query execution logic

**SQL is correct** (verified by direct execution), but something in the execution pipeline is failing to substitute parameters correctly.

## Summary

### ✅ Completed
- Fixed type mismatch bug (demographic vs demographics)
- Fixed all column name mappings
- Added dynamic SELECT field generation
- Added graceful handling of unavailable fields
- Cleared Python cache
- Restarted Streamlit apps to load new code
- End-to-end tested via Playwright

### ❌ Remaining
- Parameterized query execution returning 0 instead of 28
- Needs investigation in `SQLonFHIRAdapter.execute_sql()` or `PhenotypeValidationAgent`

### Test Evidence
- Test script: `scripts/test_sql_generation.py` - All checks pass ✅
- Direct SQL execution: Returns 28 patients ✅
- Generated SQL: Uses correct schema, tables, columns ✅
- Field mapping: Gracefully handles unavailable fields ✅

**The SQL generation bug is FIXED. The remaining issue is in query execution, not generation.**
