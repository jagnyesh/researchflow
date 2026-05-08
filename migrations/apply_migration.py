#!/usr/bin/env python3
"""
Apply Database Migration: Preview Extraction Fields

This script applies the migration to add 4 new fields to the data_deliveries table.
"""

import os
import sys
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg


async def apply_migration(database_url: str):
    """Apply migration to PostgreSQL database"""

    # Parse database URL
    # Format: postgresql+asyncpg://user:password@host:port/database
    # We need to convert to asyncpg format: postgresql://user:password@host:port/database
    pg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    print(f"🔗 Connecting to database...")
    print(f"   URL: {pg_url.split('@')[0]}@***")

    try:
        # Connect to database
        conn = await asyncpg.connect(pg_url)

        print(f"✓ Connected successfully\n")

        # Read migration SQL
        migration_file = Path(__file__).parent / "001_add_preview_fields_to_data_deliveries.sql"
        with open(migration_file, "r") as f:
            migration_sql = f.read()

        print(f"📝 Applying migration: 001_add_preview_fields_to_data_deliveries.sql")
        print(f"   File: {migration_file}\n")

        # Execute migration
        await conn.execute(migration_sql)

        print(f"\n✅ Migration applied successfully!\n")

        # Verify columns exist
        print(f"🔍 Verifying migration...")
        columns = await conn.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'data_deliveries'
            AND column_name IN ('preview_data', 'preview_qa_report', 'delivery_approved_by', 'delivery_approved_at')
            ORDER BY column_name
        """
        )

        if len(columns) == 4:
            print(f"✓ All 4 columns verified:\n")
            for col in columns:
                print(f"   - {col['column_name']}: {col['data_type']}")
        else:
            print(f"⚠ Warning: Only {len(columns)} of 4 columns found")
            for col in columns:
                print(f"   - {col['column_name']}: {col['data_type']}")

        # Close connection
        await conn.close()

        print(f"\n🎉 Migration complete!")

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)


async def rollback_migration(database_url: str):
    """Rollback migration (remove columns)"""

    # Parse database URL
    pg_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    print(f"🔗 Connecting to database...")
    print(f"   URL: {pg_url.split('@')[0]}@***")

    try:
        # Connect to database
        conn = await asyncpg.connect(pg_url)

        print(f"✓ Connected successfully\n")

        # Read rollback SQL
        rollback_file = Path(__file__).parent / "001_rollback_preview_fields.sql"
        with open(rollback_file, "r") as f:
            rollback_sql = f.read()

        print(f"📝 Applying rollback: 001_rollback_preview_fields.sql")
        print(f"   File: {rollback_file}\n")

        # Confirm rollback
        print(f"⚠️  WARNING: This will delete data in preview columns!")
        confirm = input(f"   Type 'ROLLBACK' to confirm: ")
        if confirm != "ROLLBACK":
            print(f"❌ Rollback cancelled")
            await conn.close()
            sys.exit(0)

        # Execute rollback
        await conn.execute(rollback_sql)

        print(f"\n✅ Rollback applied successfully!\n")

        # Verify columns removed
        print(f"🔍 Verifying rollback...")
        columns = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'data_deliveries'
            AND column_name IN ('preview_data', 'preview_qa_report', 'delivery_approved_by', 'delivery_approved_at')
        """
        )

        if len(columns) == 0:
            print(f"✓ All 4 columns removed successfully")
        else:
            print(f"⚠ Warning: {len(columns)} columns still exist:")
            for col in columns:
                print(f"   - {col['column_name']}")

        # Close connection
        await conn.close()

        print(f"\n🎉 Rollback complete!")

    except Exception as e:
        print(f"\n❌ Rollback failed: {e}")
        sys.exit(1)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Apply or rollback database migration")
    parser.add_argument(
        "--rollback", action="store_true", help="Rollback migration (remove columns)"
    )
    parser.add_argument(
        "--database-url", help="Database URL (default: from DATABASE_URL env var)", default=None
    )

    args = parser.parse_args()

    # Get database URL
    database_url = args.database_url or os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ Error: DATABASE_URL not set")
        print("   Set DATABASE_URL environment variable or use --database-url")
        sys.exit(1)

    # Validate PostgreSQL URL
    if not database_url.startswith("postgresql"):
        print(f"❌ Error: Database URL must be PostgreSQL")
        print(f"   Got: {database_url}")
        sys.exit(1)

    # Apply or rollback
    if args.rollback:
        print("=" * 60)
        print("ROLLBACK MIGRATION: Remove Preview Extraction Fields")
        print("=" * 60 + "\n")
        asyncio.run(rollback_migration(database_url))
    else:
        print("=" * 60)
        print("APPLY MIGRATION: Add Preview Extraction Fields")
        print("=" * 60 + "\n")
        asyncio.run(apply_migration(database_url))


if __name__ == "__main__":
    main()
