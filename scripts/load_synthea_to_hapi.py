"""
Load Synthea FHIR Bundles into HAPI FHIR Server

This script bulk-loads FHIR bundles from Synthea output directory into HAPI FHIR server.
Each bundle contains a complete patient record with all associated resources.

Usage:
    python scripts/load_synthea_to_hapi.py

Requirements:
    - HAPI FHIR server running on http://localhost:8081/fhir
    - Synthea FHIR bundles in /Users/jagnyesh/Development/sql_practice/synthea/output/fhir/
"""

import httpx
import asyncio
import json
from pathlib import Path
from datetime import datetime
import sys

# Configuration
FHIR_SERVER = "http://localhost:8081/fhir"
SYNTHEA_DIR = Path("/Users/jagnyesh/Development/sql_practice/synthea/output/fhir")
TIMEOUT = 30.0
BATCH_DELAY = 0.5  # seconds between batches
BATCH_SIZE = 10    # bundles per batch before delay


async def check_server_health() -> bool:
    """Check if HAPI FHIR server is healthy and responding"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{FHIR_SERVER}/metadata")
            return response.status_code == 200
    except Exception as e:
        print(f"❌ Server health check failed: {e}")
        return False


async def load_fhir_bundle(client: httpx.AsyncClient, bundle_path: Path) -> tuple[bool, str]:
    """
    Load a single FHIR bundle into HAPI FHIR server

    Returns:
        (success: bool, message: str)
    """
    try:
        with open(bundle_path) as f:
            bundle = json.load(f)

        # Validate it's a bundle
        if bundle.get("resourceType") != "Bundle":
            return False, f"Not a FHIR Bundle (resourceType={bundle.get('resourceType')})"

        # POST bundle to FHIR server
        response = await client.post(FHIR_SERVER, json=bundle, timeout=TIMEOUT)

        if response.status_code in [200, 201]:
            # Extract patient ID if available
            patient_id = "unknown"
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Patient":
                    patient_id = resource.get("id", "unknown")
                    break

            return True, f"Patient {patient_id}"
        else:
            return False, f"HTTP {response.status_code}: {response.text[:100]}"

    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except httpx.TimeoutException:
        return False, "Request timeout"
    except Exception as e:
        return False, f"Error: {e}"


async def load_all_bundles():
    """Load all Synthea FHIR bundles into HAPI FHIR server"""
    print("=" * 80)
    print("SYNTHEA → HAPI FHIR BULK LOADER")
    print("=" * 80)
    print(f"FHIR Server: {FHIR_SERVER}")
    print(f"Synthea Dir: {SYNTHEA_DIR}")
    print()

    # Check server health
    print("[1/4] Checking HAPI FHIR server health...")
    if not await check_server_health():
        print("❌ HAPI FHIR server is not responding")
        print("   Please ensure server is running: docker-compose up -d hapi-fhir")
        sys.exit(1)
    print("✅ HAPI FHIR server is healthy")
    print()

    # Find all bundle files
    print("[2/4] Finding FHIR bundles...")
    if not SYNTHEA_DIR.exists():
        print(f"❌ Directory not found: {SYNTHEA_DIR}")
        sys.exit(1)

    bundles = list(SYNTHEA_DIR.glob("*.json"))
    if not bundles:
        print(f"❌ No JSON files found in {SYNTHEA_DIR}")
        sys.exit(1)

    print(f"✅ Found {len(bundles)} FHIR bundles")
    print()

    # Load bundles
    print(f"[3/4] Loading {len(bundles)} bundles into HAPI FHIR...")
    print(f"   Batch size: {BATCH_SIZE} bundles")
    print(f"   Batch delay: {BATCH_DELAY}s")
    print()

    start_time = datetime.now()
    success_count = 0
    failed_count = 0

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for i, bundle_path in enumerate(bundles, 1):
            success, message = await load_fhir_bundle(client, bundle_path)

            if success:
                print(f"✅ [{i}/{len(bundles)}] {bundle_path.name} → {message}")
                success_count += 1
            else:
                print(f"❌ [{i}/{len(bundles)}] {bundle_path.name} → {message}")
                failed_count += 1

            # Batch delay to avoid overwhelming server
            if i % BATCH_SIZE == 0 and i < len(bundles):
                print(f"   ⏸️  Batch delay ({BATCH_DELAY}s)...")
                await asyncio.sleep(BATCH_DELAY)

    elapsed = (datetime.now() - start_time).total_seconds()

    # Summary
    print()
    print("=" * 80)
    print("[4/4] LOADING COMPLETE")
    print("=" * 80)
    print(f"✅ Success: {success_count}/{len(bundles)} bundles")
    if failed_count > 0:
        print(f"❌ Failed:  {failed_count}/{len(bundles)} bundles")
    print(f"⏱️  Time:    {elapsed:.1f} seconds ({elapsed/len(bundles):.2f}s per bundle)")
    print()
    print("Verify data loaded:")
    print(f"  curl {FHIR_SERVER}/Patient?_summary=count")
    print(f"  curl {FHIR_SERVER}/Condition?_summary=count")
    print(f"  curl {FHIR_SERVER}/Observation?_summary=count")
    print("=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(load_all_bundles())
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(1)
