# SQL-on-FHIR v2 API Examples

## Once HAPI FHIR Server is Running

These examples will work once you start the Docker services:

```bash
docker compose -f config/docker-compose.yml up -d
```

## Example API Requests

### 1. Health Check

```bash
curl http://localhost:8000/analytics/health | jq
```

**Expected Response:**
```json
{
 "status": "healthy",
 "fhir_server_connected": true,
 "fhir_server_url": "http://hapi-fhir:8080/fhir"
}
```

---

### 2. List All ViewDefinitions

```bash
curl http://localhost:8000/analytics/view-definitions | jq
```

**Expected Response:**
```json
{
 "view_definitions": [
 {
 "name": "patient_demographics",
 "resource_type": "Patient",
 "title": "Patient Demographics",
 "description": "Core demographic information for patients..."
 },
 {
 "name": "observation_labs",
 "resource_type": "Observation",
 "title": "Laboratory Observations",
 "description": "Laboratory test results with values, units..."
 },
 {
 "name": "condition_diagnoses",
 "resource_type": "Condition",
 "title": "Patient Conditions and Diagnoses",
 "description": "Patient conditions, diagnoses, and problems..."
 },
 {
 "name": "medication_requests",
 "resource_type": "MedicationRequest",
 "title": "Medication Orders and Prescriptions",
 "description": "Medication requests including prescriptions..."
 },
 {
 "name": "procedure_history",
 "resource_type": "Procedure",
 "title": "Procedure History",
 "description": "Patient procedures including surgeries..."
 }
 ]
}
```

---

### 3. Get Patient Demographics (All Patients)

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "patient_demographics",
 "max_resources": 10
 }' | jq
```

**Expected Response:**
```json
{
 "view_name": "patient_demographics",
 "resource_type": "Patient",
 "row_count": 10,
 "rows": [
 {
 "id": "1",
 "patient_id": "Patient/1",
 "active": true,
 "birth_date": "1980-05-15",
 "gender": "female",
 "deceased": false,
 "deceased_date": null,
 "family_name": "Smith",
 "given_name": "Jane",
 "full_name": "Jane Smith",
 "phone": "555-0123",
 "email": "jane.smith@example.com",
 "address_line": "123 Main St",
 "city": "Boston",
 "state": "Massachusetts",
 "postal_code": "02101",
 "country": "US"
 }
 ],
 "schema": {
 "id": "string",
 "patient_id": "string",
 "birth_date": "string",
 "gender": "string",
 ...
 }
}
```

---

### 4. Filter Female Patients

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "patient_demographics",
 "search_params": {
 "gender": "female"
 },
 "max_resources": 50
 }' | jq '.row_count'
```

**Expected Response:**
```
25
```

---

### 5. Get Lab Results

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "observation_labs",
 "max_resources": 20
 }' | jq '.rows[0]'
```

**Expected Response:**
```json
{
 "id": "obs-123",
 "observation_id": "Observation/obs-123",
 "patient_id": "patient-1",
 "status": "final",
 "category": "laboratory",
 "code": "2345-7",
 "code_display": "Glucose [Mass/volume] in Serum or Plasma",
 "code_text": "Glucose",
 "effective_datetime": "2024-01-15T10:30:00Z",
 "value_quantity": 95.0,
 "value_unit": "mg/dL",
 "interpretation": "N",
 "ref_range_low": 70.0,
 "ref_range_high": 100.0,
 "performer_id": "Practitioner/dr-jones"
}
```

---

### 6. Get Glucose Results Only

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "observation_labs",
 "search_params": {
 "code": "http://loinc.org|2345-7"
 },
 "max_resources": 100
 }' | jq '.rows | length'
```

**Expected Response:**
```
42
```

---

### 7. Get Conditions/Diagnoses

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "condition_diagnoses",
 "max_resources": 15
 }' | jq '.rows[0]'
```

**Expected Response:**
```json
{
 "id": "cond-456",
 "condition_id": "Condition/cond-456",
 "patient_id": "patient-1",
 "clinical_status": "active",
 "verification_status": "confirmed",
 "category": "encounter-diagnosis",
 "severity": "Moderate",
 "icd10_code": "E11.9",
 "icd10_display": "Type 2 diabetes mellitus without complications",
 "snomed_code": "44054006",
 "snomed_display": "Diabetes mellitus type 2",
 "code_text": "Type 2 Diabetes",
 "onset_datetime": "2020-03-15",
 "recorded_date": "2020-03-15T14:30:00Z",
 "encounter_id": "encounter-789"
}
```

---

### 8. Get Diabetes Diagnoses

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "condition_diagnoses",
 "search_params": {
 "code": "http://snomed.info/sct|44054006"
 }
 }' | jq
```

---

### 9. Get Medications

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "medication_requests",
 "max_resources": 10
 }' | jq '.rows[0]'
```

**Expected Response:**
```json
{
 "id": "med-789",
 "medication_request_id": "MedicationRequest/med-789",
 "patient_id": "patient-1",
 "status": "active",
 "intent": "order",
 "priority": "routine",
 "medication_code": "860975",
 "medication_display": "Metformin hydrochloride 500 MG Oral Tablet",
 "medication_text": "Metformin 500mg",
 "authored_on": "2024-01-10",
 "dosage_text": "Take 1 tablet twice daily with meals",
 "dosage_route": "Oral",
 "dosage_timing_frequency": 2,
 "dosage_timing_period": 1,
 "dosage_timing_period_unit": "d",
 "dose_quantity": 1,
 "dose_unit": "tablet",
 "dispense_quantity": 60,
 "num_refills": 3
}
```

---

### 10. Get Procedures

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "procedure_history",
 "max_resources": 10
 }' | jq '.rows[0]'
```

**Expected Response:**
```json
{
 "id": "proc-101",
 "procedure_id": "Procedure/proc-101",
 "patient_id": "patient-1",
 "status": "completed",
 "category": "Diagnostic",
 "cpt_code": "80053",
 "cpt_display": "Comprehensive metabolic panel",
 "snomed_code": "252275004",
 "snomed_display": "Comprehensive metabolic panel",
 "code_text": "Blood chemistry panel",
 "performed_datetime": "2024-01-15T09:00:00Z",
 "encounter_id": "encounter-789",
 "outcome_text": "Normal results",
 "performer_id": "Practitioner/dr-smith",
 "performer_function": "Primary performer"
}
```

---

### 11. Execute Multiple ViewDefinitions (Batch Query)

```bash
curl -X POST "http://localhost:8000/analytics/query?view_names=patient_demographics&view_names=condition_diagnoses" \
 -H "Content-Type: application/json" \
 -d '{
 "search_params": {
 "_id": "patient-1"
 },
 "max_resources": 100
 }' | jq
```

**Expected Response:**
```json
{
 "patient_demographics": {
 "resource_type": "Patient",
 "row_count": 1,
 "rows": [
 {
 "id": "patient-1",
 "patient_id": "Patient/patient-1",
 "family_name": "Smith",
 "given_name": "Jane",
 ...
 }
 ]
 },
 "condition_diagnoses": {
 "resource_type": "Condition",
 "row_count": 3,
 "rows": [
 {
 "condition_id": "Condition/cond-456",
 "patient_id": "patient-1",
 "icd10_code": "E11.9",
 ...
 },
 ...
 ]
 }
}
```

---

### 12. Get ViewDefinition Schema

```bash
curl http://localhost:8000/analytics/schema/patient_demographics | jq
```

**Expected Response:**
```json
{
 "view_name": "patient_demographics",
 "resource_type": "Patient",
 "schema": {
 "id": "string",
 "patient_id": "string",
 "active": "string",
 "birth_date": "string",
 "gender": "string",
 "deceased": "string",
 "family_name": "string",
 "given_name": "string",
 "full_name": "string",
 "phone": "string",
 "email": "string",
 "city": "string",
 "state": "string",
 "postal_code": "string",
 "country": "string"
 }
}
```

---

### 13. Create Custom ViewDefinition

```bash
curl -X POST http://localhost:8000/analytics/view-definitions \
 -H "Content-Type: application/json" \
 -d '{
 "view_definition": {
 "resourceType": "ViewDefinition",
 "resource": "Patient",
 "name": "active_adults",
 "title": "Active Adult Patients",
 "select": [
 {
 "column": [
 {"name": "id", "path": "id"},
 {"name": "gender", "path": "gender"},
 {"name": "birth_date", "path": "birthDate"}
 ]
 }
 ],
 "where": [
 {"path": "active = true"}
 ]
 }
 }' | jq
```

**Expected Response:**
```json
{
 "name": "active_adults",
 "message": "ViewDefinition 'active_adults' created successfully"
}
```

---

### 14. Execute Custom ViewDefinition

```bash
curl -X GET "http://localhost:8000/analytics/execute/active_adults?max_resources=20" | jq
```

---

## Python Client Example

```python
import httpx
import asyncio

async def get_patient_cohort():
 """Get all female patients with diabetes"""

 async with httpx.AsyncClient() as client:
 # Execute patient demographics ViewDefinition
 response = await client.post(
 "http://localhost:8000/analytics/execute",
 json={
 "view_name": "patient_demographics",
 "search_params": {"gender": "female"},
 "max_resources": 100
 }
 )

 patients_data = response.json()
 patient_ids = [row["patient_id"] for row in patients_data["rows"]]

 print(f"Found {len(patient_ids)} female patients")

 # Get conditions for these patients
 response = await client.post(
 "http://localhost:8000/analytics/execute",
 json={
 "view_name": "condition_diagnoses",
 "search_params": {
 "code": "http://snomed.info/sct|44054006" # Diabetes
 },
 "max_resources": 500
 }
 )

 conditions_data = response.json()

 # Filter for female patients
 female_diabetes = [
 row for row in conditions_data["rows"]
 if row["patient_id"] in patient_ids
 ]

 print(f"Found {len(female_diabetes)} female patients with diabetes")

 # Get their medications
 for patient_id in set(row["patient_id"] for row in female_diabetes):
 response = await client.post(
 "http://localhost:8000/analytics/execute",
 json={
 "view_name": "medication_requests",
 "search_params": {"subject": patient_id}
 }
 )

 meds = response.json()
 print(f"\n{patient_id}:")
 for med in meds["rows"]:
 print(f" - {med['medication_display']}")

# Run the analysis
asyncio.run(get_patient_cohort())
```

---

## Next Steps

1. **Start Docker Services:**
 ```bash
 docker compose -f config/docker-compose.yml up -d
 ```

2. **Load Synthetic Data:**
 ```bash
 docker compose -f config/docker-compose.yml --profile synthea up
 ```

3. **Start API Server:**
 ```bash
 uvicorn app.main:app --reload --port 8000
 ```

4. **Try the Examples Above!**

For more details, see:
- `QUICKSTART_SQL_ON_FHIR.md` - Step-by-step setup guide
- `docs/SQL_ON_FHIR_V2.md` - Complete documentation
- http://localhost:8000/docs - Interactive API documentation
