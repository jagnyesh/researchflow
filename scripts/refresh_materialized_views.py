#!/usr/bin/env python3
"""
Automated materialized view refresh pipeline.

This script refreshes all materialized views in the sqlonfhir schema.
Designed to be run as a nightly cron job to keep views up-to-date.

Usage:
    python scripts/refresh_materialized_views.py

Environment variables:
    DATABASE_URL - ResearchFlow database URL (for metadata tracking)
    HAPI_DB_URL - HAPI FHIR database URL (default: postgresql://hapi:hapi@localhost:5433/hapi)
"""
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.services.materialized_view_service import MaterializedViewService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def refresh_all_views():
    """Refresh all materialized views."""
    logger.info("=" * 60)
    logger.info("MATERIALIZED VIEW REFRESH PIPELINE")
    logger.info(f"Started at: {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    # Get database URL from environment
    database_url = os.getenv(
        'DATABASE_URL',
        'sqlite+aiosqlite:///./dev.db'
    )

    # Initialize service
    service = None
    try:
        service = await MaterializedViewService.create(database_url)

        # List all views
        views = await service.list_views()
        logger.info(f"\nFound {len(views)} materialized views to refresh")

        # Use the built-in refresh_all_views method
        logger.info("\nRefreshing all views...")
        start_time = datetime.utcnow()

        result = await service.refresh_all_views()

        duration = (datetime.utcnow() - start_time).total_seconds()

        # Log results
        logger.info("\n" + "=" * 60)
        logger.info("REFRESH COMPLETE")
        logger.info(f"Total duration: {duration:.2f}s")
        logger.info(f"Views refreshed: {result.get('refreshed_count', 0)}")
        logger.info(f"Views failed: {result.get('failed_count', 0)}")

        if result.get('errors'):
            logger.error("\nErrors encountered:")
            for error in result['errors']:
                logger.error(f"  - {error}")

        logger.info(f"Finished at: {datetime.utcnow().isoformat()}")
        logger.info("=" * 60)

        # Return exit code based on success
        return 0 if result.get('failed_count', 0) == 0 else 1

    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}", exc_info=True)
        return 1

    finally:
        # Cleanup
        if service:
            await service.db_client.close()
            await service.session.close()


def main():
    """Main entry point."""
    exit_code = asyncio.run(refresh_all_views())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
