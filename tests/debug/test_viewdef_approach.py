#!/usr/bin/env python3
"""
Test Script: Production ViewDefinition Approach

This script uses the ACTUAL production approach to query FHIR data:
1. Load ViewDefinitions (patient_demographics + condition_diagnoses)
2. Generate SQL using FHIRPath transpiler
3. Execute against HAPI database
4. Filter and combine results

This is what ResearchFlow actually does in production, NOT the theoretical
TEXT_TO_SQL_FLOW.md approach which targets non-existent flat tables.

Test Query: "count of all female patients between the age of 20 and 30 with diabetes"
"""

import asyncio
import json
from datetime import datetime, date
from typing import List, Dict, Any

# Import ResearchFlow production components
from app.clients.hapi_db_client import create_hapi_db_client, close_hapi_db_client
from app.sql_on_fhir.runner import create_postgres_runner
from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager


class ViewDefinitionTester:
    """Test harness using production ViewDefinition approach"""

    def __init__(self):
        self.db_client = None
        self.runner = None
        self.view_manager = ViewDefinitionManager()

    async def setup(self):
        """Initialize database connection and runner"""
        print("🔧 Setting up database connection...")
        self.db_client = await create_hapi_db_client()
        self.runner = await create_postgres_runner(self.db_client, enable_cache=False)
        print("✅ Connected to HAPI FHIR database\n")

    async def cleanup(self):
        """Close database connection"""
        print("\n🔧 Cleaning up...")
        await close_hapi_db_client()
        print("✅ Connection closed")

    async def query_patients(self, gender: str = None) -> tuple[List[Dict], str]:
        """
        Query patient_demographics ViewDefinition

        Returns:
            Tuple of (results, generated_sql)
        """
        print("=" * 80)
        print("PHASE 1: Query Patient Demographics")
        print("=" * 80)
        print(f"View: patient_simple (simplified demographics)")
        if gender:
            print(f"Filter: gender={gender}")
        print()

        # Load ViewDefinition (using patient_simple to avoid complex WHERE clause)
        view_def = self.view_manager.load("patient_simple")

        # Build query
        from app.sql_on_fhir.query_builder import create_sql_query_builder
        from app.sql_on_fhir.transpiler import create_fhirpath_transpiler, create_column_extractor

        transpiler = create_fhirpath_transpiler()
        extractor = create_column_extractor(transpiler)
        builder = create_sql_query_builder(transpiler, extractor)

        # Add gender filter if specified
        search_params = {"gender": gender} if gender else {}

        query = builder.build_query(view_def, search_params=search_params, limit=None)

        print("Generated SQL:")
        print("-" * 80)
        print(query.sql)
        print("-" * 80)
        print()

        # Get user confirmation
        response = input("⚠️  Execute this SQL? (yes/no): ").strip().lower()
        if response != 'yes':
            print("❌ Execution cancelled by user")
            return [], query.sql

        # Execute query
        print("\n⏳ Executing query...")
        results = await self.runner.execute(view_def, search_params=search_params)

        print(f"✅ Query executed successfully!")
        print(f"   Rows returned: {len(results)}")
        print()

        return results, query.sql

    async def query_conditions(self, patient_ids: List[str] = None) -> tuple[List[Dict], str]:
        """
        Query condition_diagnoses ViewDefinition

        Returns:
            Tuple of (results, generated_sql)
        """
        print("=" * 80)
        print("PHASE 2: Query Condition Diagnoses")
        print("=" * 80)
        print(f"View: condition_diagnoses")
        if patient_ids:
            print(f"Filter: {len(patient_ids)} patient IDs")
        print()

        # Load ViewDefinition
        view_def = self.view_manager.load("condition_diagnoses")

        # Build query
        from app.sql_on_fhir.query_builder import create_sql_query_builder
        from app.sql_on_fhir.transpiler import create_fhirpath_transpiler, create_column_extractor

        transpiler = create_fhirpath_transpiler()
        extractor = create_column_extractor(transpiler)
        builder = create_sql_query_builder(transpiler, extractor)

        # Add patient filter if specified
        # Note: This would require modifying the ViewDefinition to support patient filtering
        search_params = {}

        query = builder.build_query(view_def, search_params=search_params, limit=None)

        print("Generated SQL:")
        print("-" * 80)
        print(query.sql)
        print("-" * 80)
        print()

        # Get user confirmation
        response = input("⚠️  Execute this SQL? (yes/no): ").strip().lower()
        if response != 'yes':
            print("❌ Execution cancelled by user")
            return [], query.sql

        # Execute query
        print("\n⏳ Executing query...")
        results = await self.runner.execute(view_def, search_params=search_params)

        print(f"✅ Query executed successfully!")
        print(f"   Rows returned: {len(results)}")
        print()

        return results, query.sql

    def calculate_age(self, birth_date_str: str) -> int:
        """Calculate age from birth date string"""
        if not birth_date_str:
            return None

        try:
            birth_date = datetime.fromisoformat(birth_date_str.replace('Z', '+00:00')).date()
            today = date.today()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            return age
        except:
            return None

    def filter_by_age(self, patients: List[Dict], min_age: int, max_age: int) -> List[Dict]:
        """Filter patients by age range"""
        filtered = []
        for patient in patients:
            birth_date = patient.get('birth_date')
            if not birth_date:
                continue

            age = self.calculate_age(birth_date)
            if age is not None and min_age <= age <= max_age:
                filtered.append(patient)

        return filtered

    def filter_by_condition(self, conditions: List[Dict], keyword: str) -> List[str]:
        """
        Filter conditions by keyword and return patient IDs

        Returns:
            List of patient IDs with matching condition
        """
        patient_ids = set()

        for condition in conditions:
            # Check all text fields for keyword
            fields_to_check = [
                condition.get('icd10_display', ''),
                condition.get('snomed_display', ''),
                condition.get('code_text', ''),
                condition.get('icd10_code', ''),
                condition.get('snomed_code', '')
            ]

            for field in fields_to_check:
                if field and keyword.lower() in str(field).lower():
                    patient_id = condition.get('patient_id')
                    if patient_id:
                        patient_ids.add(patient_id)
                    break

        return list(patient_ids)

    async def run_test(self, user_query: str):
        """
        Run complete test using production ViewDefinition approach

        Query: "count of all female patients between the age of 20 and 30 with diabetes"
        """
        print("\n" + "=" * 80)
        print("ResearchFlow Production ViewDefinition Test")
        print("=" * 80)
        print(f"\n📝 User Query: {user_query}")
        print()
        print("⚠️  NOTE: This uses the PRODUCTION approach (ViewDefinitions),")
        print("   NOT the theoretical TEXT_TO_SQL_FLOW.md approach")
        print()

        await self.setup()

        try:
            # Parse query parameters
            # Query: "count of all female patients between the age of 20 and 30 with diabetes"
            gender = "female"
            min_age = 20
            max_age = 30
            condition_keyword = "diabetes"

            # STEP 1: Query patients filtered by gender
            patients, patient_sql = await self.query_patients(gender=gender)

            if not patients:
                print("❌ No patients found with specified gender")
                return

            print(f"Found {len(patients)} {gender} patients")
            print()

            # STEP 2: Filter by age (in Python, not SQL)
            print("=" * 80)
            print("PHASE 3: Filter by Age (Python)")
            print("=" * 80)
            print(f"Age range: {min_age}-{max_age}")
            print()

            patients_by_age = self.filter_by_age(patients, min_age, max_age)
            print(f"✅ Filtered to {len(patients_by_age)} patients aged {min_age}-{max_age}")
            print()

            # STEP 3: Query conditions
            conditions, condition_sql = await self.query_conditions()

            if not conditions:
                print("❌ No conditions found in database")
                return

            print(f"Found {len(conditions)} total conditions")
            print()

            # STEP 4: Filter conditions by diabetes
            print("=" * 80)
            print("PHASE 4: Filter by Condition (Python)")
            print("=" * 80)
            print(f"Condition keyword: {condition_keyword}")
            print()

            diabetes_patient_ids = self.filter_by_condition(conditions, condition_keyword)
            print(f"✅ Found {len(diabetes_patient_ids)} patients with {condition_keyword}")
            print()

            # STEP 5: Combine results
            print("=" * 80)
            print("PHASE 5: Combine Results")
            print("=" * 80)

            # Get patient IDs from age-filtered patients
            age_filtered_ids = {p.get('id') or p.get('patient_id') for p in patients_by_age}

            # Intersection: patients who are female, aged 20-30, AND have diabetes
            final_patient_ids = age_filtered_ids & set(diabetes_patient_ids)

            print(f"Female patients aged {min_age}-{max_age}: {len(age_filtered_ids)}")
            print(f"Patients with {condition_keyword}: {len(diabetes_patient_ids)}")
            print(f"Intersection: {len(final_patient_ids)}")
            print()

            # FINAL RESULT
            print("=" * 80)
            print("FINAL RESULT")
            print("=" * 80)
            print(f"Count: {len(final_patient_ids)} patients")
            print()

            if final_patient_ids:
                print("Patient IDs:")
                for pid in sorted(final_patient_ids):
                    # Find patient details
                    patient = next((p for p in patients_by_age if (p.get('id') or p.get('patient_id')) == pid), None)
                    if patient:
                        name = patient.get('full_name', 'Unknown')
                        age = self.calculate_age(patient.get('birth_date'))
                        print(f"  - {pid}: {name} (age {age})")
            else:
                print("No patients found matching all criteria")

            print()

            # Show all SQL queries
            print("=" * 80)
            print("ALL GENERATED SQL QUERIES")
            print("=" * 80)
            print("\n1. Patient Demographics SQL:")
            print("-" * 80)
            print(patient_sql)
            print("-" * 80)
            print("\n2. Condition Diagnoses SQL:")
            print("-" * 80)
            print(condition_sql)
            print("-" * 80)

        finally:
            await self.cleanup()


async def main():
    """Main entry point"""
    test_query = "count of all female patients between the age of 20 and 30 with diabetes"

    tester = ViewDefinitionTester()
    await tester.run_test(test_query)


if __name__ == "__main__":
    asyncio.run(main())
