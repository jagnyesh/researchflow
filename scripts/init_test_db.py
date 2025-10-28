#!/usr/bin/env python3
"""
Initialize Test Database for E2E Testing

Creates all tables in PostgreSQL database for end-to-end testing.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.database.models import Base


async def init_test_database():
    """Initialize test database with all tables"""

    database_url = "postgresql+asyncpg://researchflow:researchflow@localhost:5434/researchflow"

    print("=" * 80)
    print("E2E Test Database Initialization")
    print("=" * 80)
    print(f"Database URL: {database_url}")
    print()

    # Create async engine
    engine = create_async_engine(
        database_url,
        echo=True  # Show SQL statements
    )

    try:
        # Create all tables
        print("Creating database schema...")
        async with engine.begin() as conn:
            # Drop all tables first (clean slate)
            await conn.run_sync(Base.metadata.drop_all)
            print("✓ Dropped existing tables")

            # Create all tables
            await conn.run_sync(Base.metadata.create_all)
            print("✓ Created all tables")

        print()
        print("=" * 80)
        print("✅ Database initialization complete!")
        print("=" * 80)
        print()
        print("Tables created:")
        for table in Base.metadata.sorted_tables:
            print(f"  - {table.name}")
        print()

    except Exception as e:
        print(f"❌ Error initializing database: {e}", file=sys.stderr)
        raise

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init_test_database())
