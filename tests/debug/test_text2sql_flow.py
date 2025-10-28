#!/usr/bin/env python3
"""
Test Script: Text-to-SQL Flow (Following docs/TEXT_TO_SQL_FLOW.md)

This script mimics the production flow:
1. LLM Conversation (simulated for testing)
2. Structured Extraction (LLM → JSON)
3. Medical Concept Extraction
4. Template-Based SQL Generation
5. Query Execution (with confirmation)

Usage:
    python test_text2sql_flow.py
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, Any

# Import ResearchFlow components
from app.utils.llm_client import LLMClient
from app.utils.sql_generator import SQLGenerator
from app.adapters.sql_on_fhir import SQLonFHIRAdapter


class Text2SQLTester:
    """Test harness for Text-to-SQL flow"""

    def __init__(self):
        self.llm_client = LLMClient()
        self.sql_generator = SQLGenerator()
        # Use ResearchFlow database (SQLite by default)
        self.sql_adapter = SQLonFHIRAdapter("sqlite+aiosqlite:///./dev.db")

    async def run_test(self, user_query: str):
        """Run complete Text-to-SQL flow"""
        print("\n" + "="*80)
        print("TEXT-TO-SQL FLOW TEST")
        print("="*80)
        print(f"\n📝 User Query: {user_query}\n")

        # PHASE 1: Simulate conversation (in production, this is multi-turn)
        print("PHASE 1: LLM Conversation (Simulated)")
        print("-" * 80)
        conversation_history = [
            {"role": "user", "content": user_query}
        ]
        print(f"✓ Conversation started")
        print(f"  Messages: {len(conversation_history)}\n")

        # PHASE 2: Structured Extraction (LLM → JSON)
        print("PHASE 2: Structured Extraction (LLM → JSON)")
        print("-" * 80)

        # Build a simple requirements structure for testing
        # In production, this would be extracted by LLM via extract_requirements()
        structured_requirements = await self._extract_requirements_simplified(user_query)

        print(f"✓ Requirements extracted:")
        print(json.dumps(structured_requirements, indent=2))
        print()

        # PHASE 3: Medical Concept Extraction
        print("PHASE 3: Medical Concept Extraction")
        print("-" * 80)

        # Extract concepts from inclusion criteria
        print("✓ Concepts extracted and embedded in criteria:")
        for criterion in structured_requirements.get('inclusion_criteria', []):
            for concept in criterion.get('concepts', []):
                print(f"  - {concept['term']} ({concept['type']}): {concept['details']}")

        print()

        # PHASE 4: Template-Based SQL Generation
        print("PHASE 4: Template-Based SQL Generation")
        print("-" * 80)

        sql = self.sql_generator.generate_phenotype_sql(
            requirements=structured_requirements,
            count_only=True  # Based on "count of" in query
        )

        print("✓ SQL Generated:")
        print("-" * 80)
        print(sql)
        print("-" * 80)
        print()

        # PHASE 5: Query Execution (with confirmation)
        print("PHASE 5: Query Execution")
        print("-" * 80)

        # Wait for user confirmation
        response = input("⚠️  Execute this SQL? (yes/no): ").strip().lower()

        if response != 'yes':
            print("❌ Execution cancelled by user")
            return None

        try:
            print("\n⏳ Executing query...")
            results = await self.sql_adapter.execute_sql(sql)

            print(f"✅ Query executed successfully!")
            print(f"   Rows returned: {len(results)}")
            print()

            if results:
                print("RESULTS:")
                print("-" * 80)
                for i, row in enumerate(results, 1):
                    print(f"Row {i}: {json.dumps(row, default=str, indent=2)}")
                print("-" * 80)
            else:
                print("⚠️  No results found")

            return results

        except Exception as e:
            print(f"❌ SQL Execution Failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _extract_requirements_simplified(self, user_query: str) -> Dict[str, Any]:
        """
        Simplified requirements extraction for testing

        In production, this would call:
        llm_client.extract_requirements(conversation_history, current_requirements)

        For testing, we'll parse the query directly
        """
        query_lower = user_query.lower()

        # Parse the test query: "count of all female patients between the age of 20 and 30 with diabetes"
        requirements = {
            "study_title": "Test Query - Female Diabetic Patients",
            "irb_number": "TEST-IRB-001",
            "inclusion_criteria": [],
            "exclusion_criteria": [],
            "data_elements": ["patient_demographics"],
            "time_period": {},  # Empty dict, not None
            "phi_level": "de-identified"
        }

        # Parse gender - SQL generator expects criteria with concepts
        if "female" in query_lower:
            requirements["inclusion_criteria"].append({
                "text": "female patients",
                "concepts": [{
                    "term": "female",
                    "type": "demographic",
                    "details": "female patients"
                }]
            })
        elif "male" in query_lower:
            requirements["inclusion_criteria"].append({
                "text": "male patients",
                "concepts": [{
                    "term": "male",
                    "type": "demographic",
                    "details": "male patients"
                }]
            })

        # Parse age range
        if "between" in query_lower and "age" in query_lower:
            # Extract "between 20 and 30"
            import re
            age_match = re.search(r"between.*?(\d+)\s+and\s+(\d+)", query_lower)
            if age_match:
                min_age = int(age_match.group(1))
                max_age = int(age_match.group(2))
                requirements["inclusion_criteria"].append({
                    "text": f"age between {min_age} and {max_age}",
                    "concepts": [{
                        "term": "age",
                        "type": "demographic",
                        "details": f"between {min_age} and {max_age}"
                    }]
                })
        elif "over" in query_lower or "above" in query_lower:
            age_match = re.search(r"(?:over|above)\s+(\d+)", query_lower)
            if age_match:
                age = int(age_match.group(1))
                requirements["inclusion_criteria"].append({
                    "text": f"age over {age}",
                    "concepts": [{
                        "term": "age",
                        "type": "demographic",
                        "details": f"over {age}"
                    }]
                })
        elif "under" in query_lower or "below" in query_lower:
            age_match = re.search(r"(?:under|below)\s+(\d+)", query_lower)
            if age_match:
                age = int(age_match.group(1))
                requirements["inclusion_criteria"].append({
                    "text": f"age under {age}",
                    "concepts": [{
                        "term": "age",
                        "type": "demographic",
                        "details": f"under {age}"
                    }]
                })

        # Parse conditions
        if "diabetes" in query_lower or "diabetic" in query_lower:
            requirements["inclusion_criteria"].append({
                "text": "patients with diabetes",
                "concepts": [{
                    "term": "diabetes",
                    "type": "condition",
                    "details": "diabetes mellitus (any type)"
                }]
            })
        if "hypertension" in query_lower or "high blood pressure" in query_lower:
            requirements["inclusion_criteria"].append({
                "text": "patients with hypertension",
                "concepts": [{
                    "term": "hypertension",
                    "type": "condition",
                    "details": "essential hypertension"
                }]
            })

        return requirements

    async def _extract_concept_simplified(self, criterion: str) -> Dict[str, str]:
        """
        Simplified concept extraction for testing

        In production, this would call:
        llm_client.extract_medical_concepts(criterion)
        """
        criterion_lower = criterion.lower()

        # Determine concept type
        if "diabetes" in criterion_lower or "diabetic" in criterion_lower:
            return {
                "term": "diabetes",
                "type": "condition",
                "details": "diabetes mellitus (any type)"
            }
        elif "female" in criterion_lower or "male" in criterion_lower:
            return {
                "term": criterion.split()[0],
                "type": "demographic",
                "details": criterion
            }
        elif "age" in criterion_lower:
            return {
                "term": "age",
                "type": "demographic",
                "details": criterion
            }
        else:
            return {
                "term": criterion,
                "type": "unknown",
                "details": criterion
            }


async def main():
    """Main entry point"""
    print("\n" + "="*80)
    print("ResearchFlow Text-to-SQL Flow Tester")
    print("Following: docs/TEXT_TO_SQL_FLOW.md")
    print("="*80)

    # Test query
    test_query = "count of all female patients between the age of 20 and 30 with diabetes"

    print(f"\n🧪 Test Query: {test_query}")
    print()

    # Run test
    tester = Text2SQLTester()
    results = await tester.run_test(test_query)

    if results is not None:
        print("\n" + "="*80)
        print("✅ TEST COMPLETE")
        print("="*80)
    else:
        print("\n" + "="*80)
        print("❌ TEST FAILED OR CANCELLED")
        print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
