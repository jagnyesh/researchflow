#!/usr/bin/env python3
"""
Database Initialization Script

Creates all tables in the ResearchFlow database.

Usage:
    python scripts/init_database.py
    python scripts/init_database.py --drop  # Drop and recreate all tables
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import init_db, drop_db


async def main(drop_first: bool = False):
    """Initialize database tables"""
    print("=" * 80)
    print("ResearchFlow Database Initialization")
    print("=" * 80)
    print()

    if drop_first:
        print("⚠️  WARNING: Dropping all existing tables...")
        confirm = input("Are you sure? (yes/no): ")
        if confirm.lower() != "yes":
            print("❌ Cancelled")
            return 1

        print("Dropping tables...")
        await drop_db()
        print("✓ Tables dropped")
        print()

    print("Creating database tables...")
    try:
        await init_db()
        print("✓ Database initialized successfully!")
        print()
        print("Tables created:")
        print("  • research_requests")
        print("  • requirements_data")
        print("  • feasibility_reports")
        print("  • agent_executions")
        print("  • escalations")
        print("  • data_deliveries")
        print("  • audit_logs")
        print()
        print("=" * 80)
        return 0
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Initialize ResearchFlow database tables"
    )
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop all existing tables before creating new ones (DANGEROUS)"
    )

    args = parser.parse_args()

    exit_code = asyncio.run(main(drop_first=args.drop))
    sys.exit(exit_code)
