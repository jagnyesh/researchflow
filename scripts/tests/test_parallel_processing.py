#!/usr/bin/env python3
"""
Parallel Processing Performance Test

Compares sequential vs parallel resource processing to measure speedup.

Usage:
    python scripts/test_parallel_processing.py
"""

import asyncio
import sys
import time
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.clients.fhir_client import FHIRClient
from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager
from app.sql_on_fhir.runner.in_memory_runner import InMemoryRunner


async def main():
    print("=" * 80)
    print("Parallel Processing Performance Test")
    print("=" * 80)
    print()

    # Initialize
    fhir_url = "http://localhost:8081/fhir"
    client = FHIRClient(base_url=fhir_url)
    manager = ViewDefinitionManager()

    view_def = manager.load("patient_demographics")

    print("Testing with patient_demographics ViewDefinition...")
    print()

    # Test 1: Sequential processing (original)
    print("=" * 80)
    print("Test 1: Sequential Processing")
    print("=" * 80)
    runner_sequential = InMemoryRunner(
        client,
        enable_cache=False,  # Disable cache to measure raw processing speed
        parallel_processing=False  # Sequential
    )

    start = time.time()
    results_sequential = await runner_sequential.execute(view_def, max_resources=100)
    duration_sequential = time.time() - start

    print(f"Duration: {duration_sequential:.3f}s")
    print(f"Rows: {len(results_sequential)}")
    print()

    # Test 2: Parallel processing (new, batch size 10)
    print("=" * 80)
    print("Test 2: Parallel Processing (batch size 10)")
    print("=" * 80)
    runner_parallel = InMemoryRunner(
        client,
        enable_cache=False,  # Disable cache to measure raw processing speed
        parallel_processing=True,  # Parallel
        max_parallel_resources=10
    )

    start = time.time()
    results_parallel = await runner_parallel.execute(view_def, max_resources=100)
    duration_parallel = time.time() - start

    print(f"Duration: {duration_parallel:.3f}s")
    print(f"Rows: {len(results_parallel)}")
    print()

    # Test 3: Parallel processing (aggressive, batch size 20)
    print("=" * 80)
    print("Test 3: Parallel Processing (batch size 20)")
    print("=" * 80)
    runner_parallel_20 = InMemoryRunner(
        client,
        enable_cache=False,
        parallel_processing=True,
        max_parallel_resources=20
    )

    start = time.time()
    results_parallel_20 = await runner_parallel_20.execute(view_def, max_resources=100)
    duration_parallel_20 = time.time() - start

    print(f"Duration: {duration_parallel_20:.3f}s")
    print(f"Rows: {len(results_parallel_20)}")
    print()

    # Performance comparison
    speedup_10 = duration_sequential / duration_parallel if duration_parallel > 0 else 0
    speedup_20 = duration_sequential / duration_parallel_20 if duration_parallel_20 > 0 else 0

    print("=" * 80)
    print("Performance Comparison")
    print("=" * 80)
    print()
    print(f"Sequential:          {duration_sequential:.3f}s (baseline)")
    print(f"Parallel (batch 10): {duration_parallel:.3f}s ({speedup_10:.1f}x faster)")
    print(f"Parallel (batch 20): {duration_parallel_20:.3f}s ({speedup_20:.1f}x faster)")
    print()

    # Verify results are consistent
    if len(results_sequential) == len(results_parallel) == len(results_parallel_20):
        print(f"✓ All methods produced {len(results_sequential)} rows (consistent)")
    else:
        print(f"⚠ Row counts differ: sequential={len(results_sequential)}, "
              f"parallel={len(results_parallel)}, parallel_20={len(results_parallel_20)}")
    print()

    # Cleanup
    await client.close()

    print("✓ Parallel processing test complete!")
    print()

    # Summary
    print("=" * 80)
    print("Summary")
    print("=" * 80)
    print()
    print(f"Best speedup: {max(speedup_10, speedup_20):.1f}x faster with parallel processing")
    print(f"Best configuration: batch size {10 if speedup_10 > speedup_20 else 20}")
    print()

    if max(speedup_10, speedup_20) > 1.5:
        print("✅ Parallel processing provides significant speedup!")
    elif max(speedup_10, speedup_20) > 1.0:
        print("✓ Parallel processing provides moderate speedup")
    else:
        print("ℹ️ Parallel processing overhead may exceed benefit for this workload")


if __name__ == "__main__":
    asyncio.run(main())
