#!/usr/bin/env python3
"""Test Text-to-SQL with REAL HAPI FHIR data"""
import asyncio
from test_text2sql_flow import Text2SQLTester

# Override the SQL adapter to use HAPI database
class HAPITester(Text2SQLTester):
    def __init__(self):
        super().__init__()
        # Point to HAPI database instead of dev.db
        from app.adapters.sql_on_fhir import SQLonFHIRAdapter
        self.sql_adapter = SQLonFHIRAdapter("postgresql+asyncpg://hapi:hapi@localhost:5433/hapi")

async def main():
    test_query = "count of all female patients between the age of 20 and 30 with diabetes"
    print(f"\n🧪 Testing with HAPI FHIR Server (real data)")
    print(f"Query: {test_query}\n")
    
    tester = HAPITester()
    results = await tester.run_test(test_query)
    
    if results:
        print("\n✅ SUCCESS! Got results from real FHIR data")
    else:
        print("\n❌ No results (but SQL generation worked!)")

if __name__ == "__main__":
    asyncio.run(main())
