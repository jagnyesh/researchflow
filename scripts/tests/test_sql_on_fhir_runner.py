#!/usr/bin/env python3
"""
Standalone SQL-on-FHIR Test Runner

Quick test script to validate SQL-on-FHIR ViewDefinition execution against HAPI FHIR server.

Usage:
    python scripts/test_sql_on_fhir_runner.py
    python scripts/test_sql_on_fhir_runner.py --view observation_labs
    python scripts/test_sql_on_fhir_runner.py --max-resources 100
"""

import sys
import os
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from tabulate import tabulate

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.clients.fhir_client import FHIRClient
from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager
from app.sql_on_fhir.runner.in_memory_runner import InMemoryRunner


# Configuration
FHIR_SERVER_URL = os.getenv("FHIR_SERVER_URL", "http://localhost:8081/fhir")


def print_header(title: str):
    """Print formatted header"""
    print("\n" + "=" * 80)
    print(title.center(80))
    print("=" * 80 + "\n")


def print_section(title: str):
    """Print formatted section"""
    print("\n" + "-" * 80)
    print(title)
    print("-" * 80)


async def test_connection(client: FHIRClient) -> bool:
    """Test FHIR server connection"""
    print_section("1. Testing FHIR Server Connection")

    try:
        connected = await client.test_connection()
        if not connected:
            print(f"✗ Cannot connect to FHIR server at {FHIR_SERVER_URL}")
            print("\nTroubleshooting:")
            print("  1. Check if docker-compose is running:")
            print("     docker-compose -f config/docker-compose.yml ps")
            print("  2. Start services if needed:")
            print("     docker-compose -f config/docker-compose.yml up -d")
            print("  3. Check FHIR server health:")
            print(f"     curl {FHIR_SERVER_URL}/metadata")
            return False

        # Get metadata
        metadata = await client.get_metadata()
        server_name = metadata.get("software", {}).get("name", "Unknown")
        fhir_version = metadata.get("fhirVersion", "Unknown")

        print(f"✓ Connected successfully!")
        print(f"  Server: {server_name}")
        print(f"  FHIR Version: {fhir_version}")
        print(f"  Base URL: {FHIR_SERVER_URL}")

        # Check for data
        patients = await client.search("Patient", max_results=1)
        if len(patients) == 0:
            print("\n⚠ Warning: No patient data found!")
            print("  Run Synthea to generate synthetic data:")
            print("  docker-compose -f config/docker-compose.yml --profile synthea up")
            return False

        patient_count = await get_resource_count(client, "Patient")
        observation_count = await get_resource_count(client, "Observation")

        print(f"\n  Data available:")
        print(f"    Patients: {patient_count}")
        print(f"    Observations: {observation_count}")

        return True

    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False


async def get_resource_count(client: FHIRClient, resource_type: str) -> int:
    """Get approximate count of resources"""
    try:
        results = await client.search(resource_type, params={"_summary": "count"})
        return len(results)
    except:
        return 0


async def list_view_definitions(manager: ViewDefinitionManager):
    """List all available ViewDefinitions"""
    print_section("2. Available ViewDefinitions")

    view_names = manager.list()

    if not view_names:
        print("✗ No ViewDefinitions found!")
        return

    print(f"Found {len(view_names)} ViewDefinitions:\n")

    for name in view_names:
        try:
            view_def = manager.load(name)
            resource_type = view_def.get("resource")
            title = view_def.get("title", "N/A")

            # Count columns
            total_columns = sum(
                len(select_elem.get("column", []))
                for select_elem in view_def.get("select", [])
            )

            print(f"  • {name}")
            print(f"      Resource: {resource_type}")
            print(f"      Title: {title}")
            print(f"      Columns: {total_columns}")

        except Exception as e:
            print(f"  • {name} - Error loading: {e}")

    return view_names


async def execute_view_definition(
    runner: InMemoryRunner,
    manager: ViewDefinitionManager,
    view_name: str,
    max_resources: int = 20,
    search_params: dict = None
):
    """Execute a ViewDefinition and display results"""
    print_section(f"3. Executing ViewDefinition: {view_name}")

    try:
        # Load ViewDefinition
        print("Loading ViewDefinition...")
        view_def = manager.load(view_name)
        print(f"✓ Loaded: {view_def.get('title', view_name)}")
        print(f"  Resource Type: {view_def.get('resource')}")

        # Show where clauses if any
        if view_def.get("where"):
            print(f"\n  Where clauses:")
            for where in view_def["where"]:
                print(f"    - {where.get('path')}")

        # Execute
        print(f"\nExecuting ViewDefinition (max {max_resources} resources)...")
        start_time = datetime.now()

        results = await runner.execute(
            view_def,
            search_params=search_params,
            max_resources=max_resources
        )

        elapsed = (datetime.now() - start_time).total_seconds()

        print(f"✓ Execution complete!")
        print(f"  Rows returned: {len(results)}")
        print(f"  Time elapsed: {elapsed:.2f}s")
        print(f"  Throughput: {len(results)/elapsed:.1f} rows/second")

        if not results:
            print("\n⚠ No results returned")
            return

        # Display schema
        print(f"\n  Columns ({len(results[0])} total):")
        for i, col_name in enumerate(results[0].keys(), 1):
            print(f"    {i:2}. {col_name}")

        # Display sample results
        print_section("Sample Results (first 10 rows)")

        # Prepare table data
        if len(results) > 0:
            # Select subset of columns for display
            display_columns = list(results[0].keys())[:12]  # First 12 columns

            # Prepare table rows - force everything to strings
            table_data = []
            for row in results[:10]:
                table_row = []
                for col in display_columns:
                    val = row.get(col)
                    # Force string conversion for all types
                    if val is None:
                        table_row.append("")
                    elif val is True:
                        table_row.append("True")
                    elif val is False:
                        table_row.append("False")
                    elif isinstance(val, str):
                        table_row.append(val[:40] if len(val) > 40 else val)
                    else:
                        table_row.append(str(val)[:40])
                table_data.append(table_row)

            # Print table without maxcolwidths to avoid wrapping issues
            print(tabulate(
                table_data,
                headers=display_columns,
                tablefmt="grid"
            ))

        # Show detailed view of first row
        if len(results) > 0:
            print_section("Detailed View of First Row")
            first_row = results[0]

            for key, value in first_row.items():
                value_str = str(value)
                if len(value_str) > 80:
                    value_str = value_str[:77] + "..."
                print(f"  {key:30} = {value_str}")

        return results

    except FileNotFoundError:
        print(f"✗ ViewDefinition '{view_name}' not found")
        print("  Available ViewDefinitions:")
        for name in manager.list():
            print(f"    - {name}")
        return None
    except Exception as e:
        print(f"✗ Execution failed: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main(view_name: str = None, max_resources: int = 20, search_params: dict = None):
    """Main test runner"""
    print_header("SQL-on-FHIR ViewDefinition Test Runner")

    # Initialize components
    print("Initializing...")
    client = FHIRClient(base_url=FHIR_SERVER_URL)
    manager = ViewDefinitionManager()
    runner = InMemoryRunner(client)
    print("✓ Initialization complete")

    try:
        # Test connection
        connected = await test_connection(client)
        if not connected:
            return 1

        # List ViewDefinitions
        view_names = await list_view_definitions(manager)
        if not view_names:
            return 1

        # Execute ViewDefinition(s)
        if view_name:
            # Execute specific ViewDefinition
            await execute_view_definition(
                runner, manager, view_name, max_resources, search_params
            )
        else:
            # Execute default ViewDefinition
            default_view = "patient_demographics"
            if default_view in view_names:
                await execute_view_definition(
                    runner, manager, default_view, max_resources, search_params
                )

                # Offer to run more
                print("\n" + "=" * 80)
                print("\nTo test other ViewDefinitions:")
                for name in view_names:
                    if name != default_view:
                        print(f"  python scripts/test_sql_on_fhir_runner.py --view {name}")

        print_header("✓ Test Complete!")

        return 0

    except KeyboardInterrupt:
        print("\n\n✗ Interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Cleanup
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test SQL-on-FHIR ViewDefinition execution against HAPI FHIR server"
    )
    parser.add_argument(
        "--view",
        type=str,
        default=None,
        help="ViewDefinition name to execute (default: patient_demographics)"
    )
    parser.add_argument(
        "--max-resources",
        type=int,
        default=20,
        help="Maximum number of resources to process (default: 20)"
    )
    parser.add_argument(
        "--gender",
        type=str,
        choices=["male", "female"],
        help="Filter by gender (for Patient resources)"
    )

    args = parser.parse_args()

    # Build search params
    search_params = {}
    if args.gender:
        search_params["gender"] = args.gender

    # Run
    exit_code = asyncio.run(
        main(
            view_name=args.view,
            max_resources=args.max_resources,
            search_params=search_params if search_params else None
        )
    )

    sys.exit(exit_code)
