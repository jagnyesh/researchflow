#!/usr/bin/env python3
"""
Cache Performance Test

Tests the InMemoryRunner cache by running the same query multiple times
and measuring performance improvement.

Usage:
    python scripts/test_cache_performance.py
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
    print("Cache Performance Test")
    print("=" * 80)
    print()

    # Initialize
    fhir_url = "http://localhost:8081/fhir"
    client = FHIRClient(base_url=fhir_url)
    manager = ViewDefinitionManager()

    # Create runner with cache enabled
    runner = InMemoryRunner(client, enable_cache=True, cache_ttl_seconds=300)

    print("Testing cache performance with patient_demographics ViewDefinition...")
    print()

    # Load ViewDefinition
    view_def = manager.load("patient_demographics")

    # Run 1: Cache MISS (first time)
    print("Run 1: Cache MISS (fetching from FHIR server)")
    start = time.time()
    results1 = await runner.execute(view_def, max_resources=20)
    duration1 = time.time() - start
    print(f"  Duration: {duration1:.3f}s")
    print(f"  Rows: {len(results1)}")
    print()

    # Run 2: Cache HIT (same query)
    print("Run 2: Cache HIT (returning from cache)")
    start = time.time()
    results2 = await runner.execute(view_def, max_resources=20)
    duration2 = time.time() - start
    print(f"  Duration: {duration2:.3f}s")
    print(f"  Rows: {len(results2)}")
    print()

    # Run 3: Cache HIT (same query)
    print("Run 3: Cache HIT (returning from cache)")
    start = time.time()
    results3 = await runner.execute(view_def, max_resources=20)
    duration3 = time.time() - start
    print(f"  Duration: {duration3:.3f}s")
    print(f"  Rows: {len(results3)}")
    print()

    # Performance improvement
    speedup = duration1 / duration2 if duration2 > 0 else 0
    print("=" * 80)
    print(f"Performance Improvement: {speedup:.1f}x faster with cache!")
    print("=" * 80)
    print()

    # Cache statistics
    stats = runner.get_cache_stats()
    print("Cache Statistics:")
    print(f"  Cache Size: {stats['cache_size']} entries")
    print(f"  Total Requests: {stats['total_requests']}")
    print(f"  Cache Hits: {stats['cache_hits']}")
    print(f"  Cache Misses: {stats['cache_misses']}")
    print(f"  Hit Rate: {stats['hit_rate_percent']}%")
    print()

    # Cleanup
    await client.close()

    print("✓ Cache test complete!")


if __name__ == "__main__":
    asyncio.run(main())
