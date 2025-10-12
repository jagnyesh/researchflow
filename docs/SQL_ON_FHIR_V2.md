# SQL-on-FHIR v2 Implementation Guide

## Overview

ResearchFlow now includes a complete **SQL-on-FHIR v2** implementation that enables real-time analytics on FHIR data. This implementation provides:

- **ViewDefinition Management**: Create, store, and manage SQL-on-FHIR ViewDefinitions
- **In-Memory Runner**: Execute ViewDefinitions against live FHIR servers
- **Real-Time Analytics API**: RESTful endpoints for querying FHIR data in tabular format
- **Integration with Agents**: Phenotype Agent uses ViewDefinitions for cohort analysis
- **Pre-built Library**: 5 production-ready ViewDefinitions for common use cases

## Architecture

```

 ResearchFlow Application 

 Phenotype Agent ViewDefinition 
 Manager 

 In-Memory 
 Runner 

 FHIR Client 

 HAPI FHIR 
 Server 

 + Synthea Data 

```

## Components

### 1. FHIR Client (`app/clients/fhir_client.py`)

HTTP client for communicating with FHIR servers.

**Features:**
- Connection pooling
- Automatic retry with exponential backoff
- Pagination handling
- Batch/transaction support

**Example:**
```python
from app.clients.fhir_client import create_fhir_client

# Create client
client = await create_fhir_client()

# Search for patients
patients = await client.search("Patient", {"gender": "female"}, max_results=100)

# Read specific resource
patient = await client.read("Patient", "patient-123")

# Close client
await client.close()
```

### 2. ViewDefinition Manager (`app/sql_on_fhir/view_definition_manager.py`)

Manages ViewDefinition resources with CRUD operations.

**Features:**
- Load/save ViewDefinitions from JSON files
- Validation of ViewDefinition structure
- In-memory caching
- Template-based creation

**Example:**
```python
from app.sql_on_fhir import ViewDefinitionManager

manager = ViewDefinitionManager()

# Load a ViewDefinition
view_def = manager.load("patient_demographics")

# List all ViewDefinitions
names = manager.list()

# Create from template
view_def = manager.create_from_template(
 resource_type="Patient",
 name="my_custom_view",
 columns=[
 {"name": "id", "path": "id"},
 {"name": "gender", "path": "gender"}
 ],
 where=["active = true"]
)

# Save ViewDefinition
manager.save(view_def)
```

### 3. In-Memory Runner (`app/sql_on_fhir/runner/in_memory_runner.py`)

Executes ViewDefinitions by fetching FHIR resources and applying FHIRPath transformations.

**Features:**
- FHIRPath expression evaluation
- forEach/forEachOrNull handling for nested data
- Where clause filtering
- Schema extraction

**Example:**
```python
from app.clients.fhir_client import create_fhir_client
from app.sql_on_fhir import ViewDefinitionManager
from app.sql_on_fhir.runner import InMemoryRunner

# Setup
manager = ViewDefinitionManager()
view_def = manager.load("observation_labs")
client = await create_fhir_client()
runner = InMemoryRunner(client)

# Execute ViewDefinition
rows = await runner.execute(
 view_def,
 search_params={"code": "http://loinc.org|2345-7"}, # Glucose
 max_resources=1000
)

# Results are tabular
for row in rows:
 print(f"Patient: {row['patient_id']}, Value: {row['value_quantity']}")

await client.close()
```

### 4. Analytics API (`app/api/analytics.py`)

RESTful API endpoints for ViewDefinition execution.

**Endpoints:**

#### List ViewDefinitions
```bash
GET /analytics/view-definitions
```

Response:
```json
{
 "view_definitions": [
 {
 "name": "patient_demographics",
 "resource_type": "Patient",
 "title": "Patient Demographics",
 "description": "Core demographic information..."
 }
 ]
}
```

#### Get ViewDefinition
```bash
GET /analytics/view-definitions/patient_demographics
```

#### Execute ViewDefinition
```bash
POST /analytics/execute
Content-Type: application/json

{
 "view_name": "patient_demographics",
 "search_params": {"gender": "female"},
 "max_resources": 100
}
```

Response:
```json
{
 "view_name": "patient_demographics",
 "resource_type": "Patient",
 "row_count": 45,
 "rows": [
 {
 "id": "patient-1",
 "patient_id": "Patient/patient-1",
 "birth_date": "1980-05-15",
 "gender": "female",
 "family_name": "Smith",
 "given_name": "Jane"
 }
 ],
 "schema": {
 "id": "string",
 "patient_id": "string",
 "birth_date": "string",
 "gender": "string"
 }
}
```

#### Execute Multiple ViewDefinitions
```bash
POST /analytics/query?view_names=patient_demographics&view_names=condition_diagnoses
Content-Type: application/json

{
 "search_params": {"_id": "patient-123"},
 "max_resources": 1000
}
```

#### Health Check
```bash
GET /analytics/health
```

### 5. Pre-built ViewDefinitions

#### patient_demographics
Extracts core patient demographic information:
- ID, birth date, gender, deceased status
- Name (official name)
- Contact (phone, email)
- Address (home address)

#### observation_labs
Laboratory test results:
- LOINC codes
- Numeric values with units
- Reference ranges
- Interpretation codes

#### condition_diagnoses
Patient conditions and diagnoses:
- ICD-10-CM codes
- SNOMED CT codes
- Clinical status
- Onset and resolution dates

#### medication_requests
Medication orders and prescriptions:
- RxNorm codes
- Dosage instructions
- Timing and frequency
- Dispense information

#### procedure_history
Procedures and interventions:
- CPT codes
- SNOMED CT procedure codes
- Performers and roles
- Body sites

## Integration with Phenotype Agent

The Phenotype Agent now supports ViewDefinition-based cohort estimation:

```python
from app.agents.phenotype_agent import PhenotypeValidationAgent

agent = PhenotypeValidationAgent()

# Use ViewDefinitions for cohort estimation
agent.use_view_definitions = True

# Estimate cohort size
cohort_size = await agent._estimate_cohort_size_with_view_definitions(requirements)

# Execute ViewDefinition for specific resource type
conditions = await agent.execute_view_definition_for_phenotype(
 "condition_diagnoses",
 requirements,
 max_resources=5000
)
```

## Setup and Deployment

### 1. Start HAPI FHIR Server with Docker Compose

```bash
# Start all services (app, HAPI FHIR, PostgreSQL)
docker-compose -f config/docker-compose.yml up -d

# Wait for HAPI FHIR to be healthy (check logs)
docker logs -f hapi-fhir-server

# Load synthetic data (run once)
docker-compose -f config/docker-compose.yml --profile synthea up
```

**Services:**
- HAPI FHIR Server: http://localhost:8081/fhir
- HAPI FHIR UI: http://localhost:8081
- ResearchFlow API: http://localhost:8000
- PostgreSQL (HAPI): localhost:5433
- PostgreSQL (App): localhost:5432

### 2. Install Dependencies

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies (includes fhirpathpy and tenacity)
pip install -r config/requirements.txt
```

### 3. Configure Environment

```bash
# Add to .env file
FHIR_SERVER_URL=http://localhost:8081/fhir
```

### 4. Test Connection

```bash
# Test FHIR server connection
curl http://localhost:8081/fhir/metadata

# Test analytics API
curl http://localhost:8000/analytics/health
```

## Usage Examples

### Example 1: Get Female Patients

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "patient_demographics",
 "search_params": {"gender": "female"},
 "max_resources": 50
 }'
```

### Example 2: Get Glucose Lab Results

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "observation_labs",
 "search_params": {
 "code": "http://loinc.org|2345-7",
 "status": "final"
 },
 "max_resources": 100
 }'
```

### Example 3: Get Diabetes Diagnoses

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "condition_diagnoses",
 "search_params": {
 "code": "http://snomed.info/sct|44054006"
 },
 "max_resources": 200
 }'
```

### Example 4: Create Custom ViewDefinition

```python
import httpx

view_def = {
 "resourceType": "ViewDefinition",
 "resource": "Patient",
 "name": "active_adults",
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
 {"path": "active = true"},
 {"path": "birthDate <= today() - 18 years"}
 ]
}

response = httpx.post(
 "http://localhost:8000/analytics/view-definitions",
 json={"view_definition": view_def}
)

print(response.json())
```

## Performance Considerations

### In-Memory Runner

**Pros:**
- Simple implementation
- Works with any FHIR server
- No database schema changes needed

**Cons:**
- Slower for large datasets
- Fetches all resources over HTTP
- Limited by network and memory

**Best for:**
- Small to medium datasets (< 10,000 resources)
- Ad-hoc queries
- Development and testing

### Future: In-Database Runner

For production workloads with large datasets, consider implementing an in-database runner that transpiles ViewDefinitions to native PostgreSQL queries.

**Benefits:**
- 10-100x faster query execution
- Leverage database indexes
- Support for complex joins and aggregations

**Trade-offs:**
- More complex implementation
- Requires FHIR data to be stored in database
- Database-specific SQL generation

## Troubleshooting

### FHIR Server Connection Failed

```bash
# Check if HAPI FHIR is running
docker ps | grep hapi-fhir

# Check FHIR server logs
docker logs hapi-fhir-server

# Test connection manually
curl http://localhost:8081/fhir/metadata
```

### No Data Returned

```bash
# Check if synthetic data was loaded
curl http://localhost:8081/fhir/Patient?_count=10

# Run Synthea to generate data
docker-compose -f config/docker-compose.yml --profile synthea up
```

### FHIRPath Evaluation Errors

FHIRPath expressions must be valid according to the FHIR specification. Common issues:

- Incorrect path syntax
- Missing field in resource
- Type mismatches

Check ViewDefinition validation errors:
```python
manager = ViewDefinitionManager()
try:
 manager.validate(view_def)
except ValueError as e:
 print(f"Validation error: {e}")
```

## Next Steps

1. **Create Custom ViewDefinitions** for your specific phenotypes
2. **Implement In-Database Runner** for production performance
3. **Add Materialized Views** for frequently-used queries
4. **Integrate with BI Tools** (Tableau, PowerBI) via analytics API
5. **Build Real-Time Dashboards** using Streamlit with ViewDefinitions

## References

- [SQL-on-FHIR v2 Specification](https://build.fhir.org/ig/FHIR/sql-on-fhir-v2/)
- [FHIR R4 Specification](https://hl7.org/fhir/R4/)
- [FHIRPath Specification](https://hl7.org/fhirpath/)
- [HAPI FHIR Documentation](https://hapifhir.io/)
- [Synthea Synthetic Patient Generator](https://github.com/synthetichealth/synthea)
