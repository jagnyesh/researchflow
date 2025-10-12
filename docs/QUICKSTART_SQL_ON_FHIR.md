# SQL-on-FHIR v2 Quick Start Guide

## Get Started in 5 Minutes

This guide will help you set up and run the SQL-on-FHIR v2 implementation with HAPI FHIR server and synthetic data.

## Prerequisites

- Docker and Docker Compose installed
- Python 3.11+ (for local development)
- 8GB RAM minimum
- 10GB disk space

## Step 1: Start HAPI FHIR Server (2 minutes)

```bash
# Navigate to project directory
cd /Users/jagnyesh/Development/FHIR_PROJECT

# Start HAPI FHIR server with PostgreSQL
docker-compose -f config/docker-compose.yml up -d hapi-fhir hapi-db

# Wait for server to be healthy (check logs)
docker logs -f hapi-fhir-server

# You should see: "Started Application in X seconds"
# Press Ctrl+C to exit logs
```

**Verify:** Open http://localhost:8081 in your browser - you should see the HAPI FHIR web interface.

## Step 2: Load Synthetic Data (3-5 minutes)

```bash
# Generate 100 synthetic patients using Synthea
docker-compose -f config/docker-compose.yml --profile synthea up

# This will:
# - Generate 100 patients
# - Create associated observations, conditions, medications, procedures
# - Upload all data to HAPI FHIR server
# - Exit when complete

# Verify data was loaded
curl "http://localhost:8081/fhir/Patient?_count=10&_pretty=true"

# You should see 10 patient resources
```

## Step 3: Install Python Dependencies (1 minute)

```bash
# Create/activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r config/requirements.txt

# This installs:
# - FastAPI for API server
# - fhirpathpy for FHIRPath evaluation
# - httpx for FHIR client
# - tenacity for retry logic
# - All other ResearchFlow dependencies
```

## Step 4: Configure Environment

```bash
# Create .env file if it doesn't exist
cp config/.env.example .env

# Add/verify FHIR server URL in .env
echo "FHIR_SERVER_URL=http://localhost:8081/fhir" >> .env
```

## Step 5: Start ResearchFlow API (1 minute)

```bash
# Start API server
uvicorn app.main:app --reload --port 8000

# You should see:
# INFO: Uvicorn running on http://127.0.0.1:8000
# INFO: Application startup complete
```

## Step 6: Test the Analytics API

### Test 1: Health Check

```bash
# In a new terminal
curl http://localhost:8000/analytics/health | jq

# Expected output:
{
 "status": "healthy",
 "fhir_server_connected": true,
 "fhir_server_url": "http://localhost:8081/fhir"
}
```

### Test 2: List Available ViewDefinitions

```bash
curl http://localhost:8000/analytics/view-definitions | jq

# Expected output:
{
 "view_definitions": [
 {
 "name": "patient_demographics",
 "resource_type": "Patient",
 "title": "Patient Demographics",
 "description": "Core demographic information..."
 },
 {
 "name": "observation_labs",
 "resource_type": "Observation",
 ...
 },
 ...
 ]
}
```

### Test 3: Execute a ViewDefinition

```bash
# Get patient demographics
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "patient_demographics",
 "max_resources": 10
 }' | jq

# Expected output:
{
 "view_name": "patient_demographics",
 "resource_type": "Patient",
 "row_count": 10,
 "rows": [
 {
 "id": "1",
 "patient_id": "Patient/1",
 "birth_date": "1980-05-15",
 "gender": "female",
 "family_name": "Smith",
 "given_name": "Jane",
 "full_name": "Jane Smith",
 "city": "Boston",
 "state": "Massachusetts"
 },
 ...
 ],
 "schema": { ... }
}
```

### Test 4: Filter Results

```bash
# Get only female patients
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "patient_demographics",
 "search_params": {"gender": "female"},
 "max_resources": 5
 }' | jq '.row_count'

# Should return: 5 (or fewer if less than 5 female patients)
```

### Test 5: Get Lab Results

```bash
# Get all lab observations
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "observation_labs",
 "max_resources": 20
 }' | jq '.rows[0]'

# Expected output shows a lab result with:
# - patient_id
# - code (LOINC code)
# - code_display
# - value_quantity
# - value_unit
# - effective_datetime
```

## Step 7: Explore the Data

### Interactive API Documentation

Open http://localhost:8000/docs in your browser to see:
- All API endpoints
- Interactive testing interface
- Request/response schemas
- Try out different queries

### Common Queries

#### Get all conditions for a specific patient

```bash
# First, get a patient ID
PATIENT_ID=$(curl -s "http://localhost:8081/fhir/Patient?_count=1" | jq -r '.entry[0].resource.id')

# Get their conditions
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d "{
 \"view_name\": \"condition_diagnoses\",
 \"search_params\": {\"subject\": \"Patient/$PATIENT_ID\"}
 }" | jq
```

#### Get medications for all patients

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "medication_requests",
 "max_resources": 50
 }' | jq '.rows[] | {patient_id, medication_display, dosage_text}'
```

#### Get procedures performed

```bash
curl -X POST http://localhost:8000/analytics/execute \
 -H "Content-Type: application/json" \
 -d '{
 "view_name": "procedure_history",
 "max_resources": 30
 }' | jq '.rows[] | {patient_id, code_text, performed_datetime}'
```

## Step 8: Use in Python Code

```python
import httpx
import asyncio

async def analyze_patient_cohort():
 async with httpx.AsyncClient() as client:
 # Get all female patients over 40
 response = await client.post(
 "http://localhost:8000/analytics/execute",
 json={
 "view_name": "patient_demographics",
 "search_params": {"gender": "female"},
 "max_resources": 100
 }
 )

 patients = response.json()
 print(f"Found {patients['row_count']} female patients")

 # Calculate average age (simplified)
 from datetime import datetime
 total_age = 0
 for patient in patients['rows']:
 if patient.get('birth_date'):
 birth_year = int(patient['birth_date'][:4])
 age = datetime.now().year - birth_year
 if age > 40:
 total_age += age

 if total_age > 0:
 avg_age = total_age / patients['row_count']
 print(f"Average age: {avg_age:.1f} years")

# Run the analysis
asyncio.run(analyze_patient_cohort())
```

## Next Steps

1. **Explore the Full Documentation**: See `docs/SQL_ON_FHIR_V2.md` for complete details

2. **Create Custom ViewDefinitions**: Modify or create new ViewDefinitions in `app/sql_on_fhir/view_definitions/`

3. **Integrate with ResearchFlow**: Use ViewDefinitions in your research workflows via the Phenotype Agent

4. **Build Dashboards**: Create Streamlit dashboards using the analytics API

5. **Add More Data**: Generate more synthetic patients:
 ```bash
 # Edit docker-compose.yml to change POPULATION from 100 to 1000
 # Then re-run:
 docker-compose -f config/docker-compose.yml --profile synthea up
 ```

## Troubleshooting

### Port Already in Use

```bash
# If port 8081 is already used
# Edit docker-compose.yml and change:
# ports: - "8082:8080" # Instead of 8081:8080

# Update .env:
# FHIR_SERVER_URL=http://localhost:8082/fhir
```

### No Data Returned

```bash
# Check if HAPI FHIR has data
curl "http://localhost:8081/fhir/Patient?_count=1"

# If empty, re-run Synthea:
docker-compose -f config/docker-compose.yml --profile synthea up
```

### FHIRPath Errors

The in-memory runner uses FHIRPath expressions. If you see evaluation errors:

1. Check ViewDefinition syntax
2. Verify resource has expected fields
3. Review FHIRPath spec: https://hl7.org/fhirpath/

### Docker Issues

```bash
# Stop all containers
docker-compose -f config/docker-compose.yml down

# Remove volumes and start fresh
docker-compose -f config/docker-compose.yml down -v

# Rebuild and start
docker-compose -f config/docker-compose.yml up -d --build
```

## Architecture Summary

```

 Your Query 
 (HTTP Request) 

 Analytics API 
 (FastAPI) 

 ViewDefinition 
 Runner 
 (in-memory) 

 FHIR Client 
 (HTTP + Retry) 

 HAPI FHIR 
 (PostgreSQL) 

 + Synthea Data 

```

## Resources

- **Full Documentation**: `docs/SQL_ON_FHIR_V2.md`
- **ViewDefinition Specs**: https://build.fhir.org/ig/FHIR/sql-on-fhir-v2/
- **HAPI FHIR Docs**: https://hapifhir.io/
- **FHIRPath Spec**: https://hl7.org/fhirpath/
- **Synthea**: https://github.com/synthetichealth/synthea

## Support

For questions or issues:
1. Check the full documentation
2. Review HAPI FHIR logs: `docker logs hapi-fhir-server`
3. Test FHIR server directly: http://localhost:8081
4. Verify ViewDefinition syntax using the validation endpoint

Enjoy exploring FHIR data with SQL-on-FHIR v2! 
