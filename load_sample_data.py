"""
Load sample FHIR data into HAPI FHIR server.

Creates synthetic patients, observations, conditions, medications, and procedures.
"""

import httpx
import json
from datetime import datetime, timedelta
import random

FHIR_BASE_URL = "http://localhost:8081/fhir"

# Sample data for generation
FAMILY_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez"]
GIVEN_NAMES_M = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Christopher"]
GIVEN_NAMES_F = ["Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen"]

CITIES = ["Boston", "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia", "San Antonio", "San Diego", "Dallas"]
STATES = ["MA", "NY", "CA", "IL", "TX", "AZ", "PA", "TX", "CA", "TX"]

# Lab test LOINC codes
LAB_CODES = [
    {"code": "2345-7", "display": "Glucose [Mass/volume] in Serum or Plasma", "unit": "mg/dL", "low": 70, "high": 100},
    {"code": "2093-3", "display": "Cholesterol [Mass/volume] in Serum or Plasma", "unit": "mg/dL", "low": 125, "high": 200},
    {"code": "6690-2", "display": "Leukocytes [#/volume] in Blood by Automated count", "unit": "10*3/uL", "low": 4.5, "high": 11.0},
    {"code": "789-8", "display": "Erythrocytes [#/volume] in Blood by Automated count", "unit": "10*6/uL", "low": 4.2, "high": 5.9},
]

# Condition SNOMED codes
CONDITION_CODES = [
    {"snomed": "44054006", "icd10": "E11.9", "display": "Type 2 diabetes mellitus"},
    {"snomed": "38341003", "icd10": "I10", "display": "Hypertension"},
    {"snomed": "13645005", "icd10": "E78.5", "display": "Hyperlipidemia"},
    {"snomed": "195967001", "icd10": "J45.909", "display": "Asthma"},
]

# Medication RxNorm codes
MEDICATION_CODES = [
    {"code": "860975", "display": "Metformin hydrochloride 500 MG Oral Tablet"},
    {"code": "197361", "display": "Lisinopril 10 MG Oral Tablet"},
    {"code": "617310", "display": "Atorvastatin 20 MG Oral Tablet"},
    {"code": "745678", "display": "Albuterol 0.09 MG/ACTUAT Metered Dose Inhaler"},
]

# Procedure CPT/SNOMED codes
PROCEDURE_CODES = [
    {"cpt": "80053", "snomed": "252275004", "display": "Comprehensive metabolic panel"},
    {"cpt": "80061", "snomed": "252279005", "display": "Lipid panel"},
    {"cpt": "85025", "snomed": "26604007", "display": "Complete blood count"},
]


def create_patient(index):
    """Create a sample patient resource."""
    gender = random.choice(["male", "female"])
    given_name = random.choice(GIVEN_NAMES_M if gender == "male" else GIVEN_NAMES_F)
    family_name = random.choice(FAMILY_NAMES)

    birth_year = random.randint(1950, 2010)
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    birth_date = f"{birth_year}-{birth_month:02d}-{birth_day:02d}"

    city_index = random.randint(0, len(CITIES) - 1)

    patient = {
        "resourceType": "Patient",
        "id": f"patient-{index}",
        "active": True,
        "name": [
            {
                "use": "official",
                "family": family_name,
                "given": [given_name]
            }
        ],
        "gender": gender,
        "birthDate": birth_date,
        "address": [
            {
                "use": "home",
                "line": [f"{random.randint(100, 9999)} Main St"],
                "city": CITIES[city_index],
                "state": STATES[city_index],
                "postalCode": f"{random.randint(10000, 99999)}",
                "country": "US"
            }
        ],
        "telecom": [
            {
                "system": "phone",
                "value": f"555-{random.randint(1000, 9999)}",
                "use": "home"
            },
            {
                "system": "email",
                "value": f"{given_name.lower()}.{family_name.lower()}@example.com",
                "use": "home"
            }
        ]
    }

    return patient


def create_observation(patient_id, lab_code):
    """Create a sample observation (lab result) resource."""
    obs_id = f"obs-{patient_id}-{lab_code['code']}"

    # Random value within normal range or slightly outside
    value = random.uniform(lab_code['low'] * 0.9, lab_code['high'] * 1.1)

    # Determine interpretation
    if value < lab_code['low']:
        interpretation = "L"
    elif value > lab_code['high']:
        interpretation = "H"
    else:
        interpretation = "N"

    # Random date in past 6 months
    days_ago = random.randint(1, 180)
    effective_date = (datetime.now() - timedelta(days=days_ago)).isoformat() + "Z"

    observation = {
        "resourceType": "Observation",
        "id": obs_id,
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                        "display": "Laboratory"
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": lab_code['code'],
                    "display": lab_code['display']
                }
            ],
            "text": lab_code['display']
        },
        "subject": {
            "reference": f"Patient/{patient_id}"
        },
        "effectiveDateTime": effective_date,
        "valueQuantity": {
            "value": round(value, 2),
            "unit": lab_code['unit'],
            "system": "http://unitsofmeasure.org",
            "code": lab_code['unit']
        },
        "interpretation": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                        "code": interpretation,
                        "display": "Normal" if interpretation == "N" else ("Low" if interpretation == "L" else "High")
                    }
                ]
            }
        ],
        "referenceRange": [
            {
                "low": {
                    "value": lab_code['low'],
                    "unit": lab_code['unit']
                },
                "high": {
                    "value": lab_code['high'],
                    "unit": lab_code['unit']
                }
            }
        ]
    }

    return observation


def create_condition(patient_id, index, condition_code):
    """Create a sample condition resource."""
    cond_id = f"cond-{patient_id}-{index}"

    # Random onset date in past 2 years
    days_ago = random.randint(30, 730)
    onset_date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")

    condition = {
        "resourceType": "Condition",
        "id": cond_id,
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                    "display": "Active"
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                    "display": "Confirmed"
                }
            ]
        },
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                        "code": "encounter-diagnosis",
                        "display": "Encounter Diagnosis"
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": condition_code['snomed'],
                    "display": condition_code['display']
                },
                {
                    "system": "http://hl7.org/fhir/sid/icd-10",
                    "code": condition_code['icd10'],
                    "display": condition_code['display']
                }
            ],
            "text": condition_code['display']
        },
        "subject": {
            "reference": f"Patient/{patient_id}"
        },
        "onsetDateTime": onset_date,
        "recordedDate": onset_date
    }

    return condition


def create_medication_request(patient_id, index, med_code):
    """Create a sample medication request resource."""
    med_id = f"med-{patient_id}-{index}"

    # Random authored date in past 6 months
    days_ago = random.randint(1, 180)
    authored_date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")

    medication_request = {
        "resourceType": "MedicationRequest",
        "id": med_id,
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": med_code['code'],
                    "display": med_code['display']
                }
            ],
            "text": med_code['display']
        },
        "subject": {
            "reference": f"Patient/{patient_id}"
        },
        "authoredOn": authored_date,
        "dosageInstruction": [
            {
                "text": "Take 1 tablet once daily",
                "timing": {
                    "repeat": {
                        "frequency": 1,
                        "period": 1,
                        "periodUnit": "d"
                    }
                },
                "route": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "26643006",
                            "display": "Oral"
                        }
                    ]
                },
                "doseAndRate": [
                    {
                        "doseQuantity": {
                            "value": 1,
                            "unit": "tablet"
                        }
                    }
                ]
            }
        ]
    }

    return medication_request


def create_procedure(patient_id, index, proc_code):
    """Create a sample procedure resource."""
    proc_id = f"proc-{patient_id}-{index}"

    # Random performed date in past 3 months
    days_ago = random.randint(1, 90)
    performed_date = (datetime.now() - timedelta(days=days_ago)).isoformat() + "Z"

    procedure = {
        "resourceType": "Procedure",
        "id": proc_id,
        "status": "completed",
        "category": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "103693007",
                    "display": "Diagnostic procedure"
                }
            ]
        },
        "code": {
            "coding": [
                {
                    "system": "http://www.ama-assn.org/go/cpt",
                    "code": proc_code['cpt'],
                    "display": proc_code['display']
                },
                {
                    "system": "http://snomed.info/sct",
                    "code": proc_code['snomed'],
                    "display": proc_code['display']
                }
            ],
            "text": proc_code['display']
        },
        "subject": {
            "reference": f"Patient/{patient_id}"
        },
        "performedDateTime": performed_date
    }

    return procedure


async def upload_resource(client, resource):
    """Upload a FHIR resource using PUT (with ID)."""
    resource_type = resource['resourceType']
    resource_id = resource['id']
    url = f"{FHIR_BASE_URL}/{resource_type}/{resource_id}"

    try:
        response = await client.put(url, json=resource)
        response.raise_for_status()
        print(f"✓ Created {resource_type}/{resource_id}")
        return True
    except Exception as e:
        print(f"✗ Failed to create {resource_type}/{resource_id}: {e}")
        return False


async def main():
    """Generate and upload sample FHIR data."""
    print("=" * 70)
    print("Loading Sample FHIR Data into HAPI FHIR Server")
    print("=" * 70)
    print()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Test FHIR server connection
        print("1. Testing FHIR server connection...")
        try:
            response = await client.get(f"{FHIR_BASE_URL}/metadata")
            response.raise_for_status()
            print(f"   ✓ FHIR server connected: {FHIR_BASE_URL}")
        except Exception as e:
            print(f"   ✗ Cannot connect to FHIR server: {e}")
            return
        print()

        # Create 10 patients
        print("2. Creating patients...")
        patient_ids = []
        for i in range(1, 11):
            patient = create_patient(i)
            patient_id = patient['id']
            if await upload_resource(client, patient):
                patient_ids.append(patient_id)
        print(f"   Created {len(patient_ids)} patients")
        print()

        # Create observations for each patient
        print("3. Creating lab observations...")
        obs_count = 0
        for patient_id in patient_ids:
            # 2 random lab tests per patient
            for _ in range(2):
                lab_code = random.choice(LAB_CODES)
                observation = create_observation(patient_id, lab_code)
                if await upload_resource(client, observation):
                    obs_count += 1
        print(f"   Created {obs_count} observations")
        print()

        # Create conditions for some patients
        print("4. Creating conditions...")
        cond_count = 0
        for patient_id in random.sample(patient_ids, min(7, len(patient_ids))):
            # 1-2 conditions per patient
            num_conditions = random.randint(1, 2)
            for i in range(num_conditions):
                condition_code = random.choice(CONDITION_CODES)
                condition = create_condition(patient_id, i, condition_code)
                if await upload_resource(client, condition):
                    cond_count += 1
        print(f"   Created {cond_count} conditions")
        print()

        # Create medication requests for patients with conditions
        print("5. Creating medication requests...")
        med_count = 0
        for patient_id in random.sample(patient_ids, min(6, len(patient_ids))):
            # 1-2 medications per patient
            num_meds = random.randint(1, 2)
            for i in range(num_meds):
                med_code = random.choice(MEDICATION_CODES)
                medication_request = create_medication_request(patient_id, i, med_code)
                if await upload_resource(client, medication_request):
                    med_count += 1
        print(f"   Created {med_count} medication requests")
        print()

        # Create procedures
        print("6. Creating procedures...")
        proc_count = 0
        for patient_id in random.sample(patient_ids, min(8, len(patient_ids))):
            proc_code = random.choice(PROCEDURE_CODES)
            procedure = create_procedure(patient_id, 0, proc_code)
            if await upload_resource(client, procedure):
                proc_count += 1
        print(f"   Created {proc_count} procedures")
        print()

        print("=" * 70)
        print("✓ Sample Data Loading Complete!")
        print("=" * 70)
        print()
        print("Summary:")
        print(f"  - Patients: {len(patient_ids)}")
        print(f"  - Lab Observations: {obs_count}")
        print(f"  - Conditions: {cond_count}")
        print(f"  - Medication Requests: {med_count}")
        print(f"  - Procedures: {proc_count}")
        print()
        print("Next Steps:")
        print("  1. Start ResearchFlow API:")
        print("     uvicorn app.main:app --reload --port 8000")
        print()
        print("  2. Test Analytics API:")
        print("     curl http://localhost:8000/analytics/health")
        print()
        print("  3. Execute ViewDefinition:")
        print('     curl -X POST http://localhost:8000/analytics/execute \\')
        print('       -H "Content-Type: application/json" \\')
        print('       -d \'{"view_name": "patient_demographics", "max_resources": 10}\' | jq')
        print()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
