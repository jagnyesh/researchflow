"""
Materialized View Service

Business logic layer for managing materialized views in the 'sqlonfhir' schema.

Responsibilities:
- Create, refresh, drop materialized views
- Track view metadata (last refresh, row count, size)
- Monitor view health and staleness
- Execute view management operations
- Integration with scripts/create_materialized_views.py
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path

from app.clients.hapi_db_client import HAPIDBClient, create_hapi_db_client
from app.database.models import MaterializedViewMetadata
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

logger = logging.getLogger(__name__)


class MaterializedViewService:
    """
    Service for managing materialized views

    Provides high-level operations for creating, refreshing, and monitoring
    materialized views in the 'sqlonfhir' schema.
    """

    SCHEMA_NAME = "sqlonfhir"
    STALENESS_THRESHOLD_HOURS = 24  # Views older than this are considered stale

    def __init__(self, hapi_db_client: HAPIDBClient, session: AsyncSession):
        """
        Initialize service

        Args:
            hapi_db_client: HAPI database client for direct SQL execution
            session: SQLAlchemy async session for metadata tracking
        """
        self.db_client = hapi_db_client
        self.session = session

    @classmethod
    async def create(cls, database_url: str):
        """
        Factory method to create service instance

        Args:
            database_url: Database connection string (for metadata)

        Returns:
            MaterializedViewService instance
        """
        # Create HAPI DB client for SQL execution
        hapi_db_client = await create_hapi_db_client()

        # Create async session for metadata tracking
        engine = create_async_engine(database_url, echo=False)
        async_session_maker = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        session = async_session_maker()

        return cls(hapi_db_client, session)

    async def list_views(self) -> List[Dict[str, Any]]:
        """
        List all materialized views with metadata

        Returns:
            List of view metadata dictionaries
        """
        try:
            # Query PostgreSQL for materialized views
            sql = f"""
                SELECT
                    matviewname as view_name,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||matviewname)) as size,
                    pg_total_relation_size(schemaname||'.'||matviewname) as size_bytes
                FROM pg_matviews
                WHERE schemaname = '{self.SCHEMA_NAME}'
                ORDER BY matviewname
            """

            pg_views = await self.db_client.execute_query(sql)

            # Get metadata from our tracking table
            result = await self.session.execute(
                select(MaterializedViewMetadata)
            )
            metadata_map = {m.view_name: m for m in result.scalars().all()}

            # Combine PostgreSQL data with our metadata
            views = []
            for pg_view in pg_views:
                view_name = pg_view['view_name']
                metadata = metadata_map.get(view_name)

                # Get row count
                count_sql = f"SELECT COUNT(*) as count FROM {self.SCHEMA_NAME}.{view_name}"
                count_result = await self.db_client.execute_query(count_sql)
                row_count = count_result[0]['count'] if count_result else 0

                view_info = {
                    "view_name": view_name,
                    "row_count": row_count,
                    "size": pg_view.get('size'),
                    "size_bytes": pg_view.get('size_bytes'),
                    "status": metadata.status if metadata else "unknown",
                    "last_refreshed_at": metadata.last_refreshed_at.isoformat() if metadata and metadata.last_refreshed_at else None,
                    "is_stale": metadata.is_stale if metadata else False,
                    "staleness_hours": metadata.staleness_hours if metadata else None,
                    "resource_type": metadata.resource_type if metadata else None
                }

                views.append(view_info)

            logger.info(f"Listed {len(views)} materialized views")
            return views

        except Exception as e:
            logger.error(f"Failed to list views: {e}")
            raise

    async def get_view_status(self, view_name: str) -> Dict[str, Any]:
        """
        Get detailed status for a specific view

        Args:
            view_name: Name of the view

        Returns:
            View status dictionary
        """
        try:
            # Check if view exists in PostgreSQL
            exists_sql = f"""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_matviews
                    WHERE schemaname = '{self.SCHEMA_NAME}'
                      AND matviewname = '{view_name}'
                ) as exists
            """

            result = await self.db_client.execute_query(exists_sql)
            exists = result[0]['exists'] if result else False

            if not exists:
                return {
                    "view_name": view_name,
                    "exists": False,
                    "status": "not_found"
                }

            # Get metadata
            stmt = select(MaterializedViewMetadata).where(
                MaterializedViewMetadata.view_name == view_name
            )
            result = await self.session.execute(stmt)
            metadata = result.scalar_one_or_none()

            # Get row count and size
            count_sql = f"SELECT COUNT(*) as count FROM {self.SCHEMA_NAME}.{view_name}"
            count_result = await self.db_client.execute_query(count_sql)
            row_count = count_result[0]['count'] if count_result else 0

            size_sql = f"""
                SELECT pg_size_pretty(pg_total_relation_size('{self.SCHEMA_NAME}.{view_name}')) as size,
                       pg_total_relation_size('{self.SCHEMA_NAME}.{view_name}') as size_bytes
            """
            size_result = await self.db_client.execute_query(size_sql)
            size_info = size_result[0] if size_result else {}

            status = {
                "view_name": view_name,
                "exists": True,
                "row_count": row_count,
                "size": size_info.get('size'),
                "size_bytes": size_info.get('size_bytes'),
                "status": metadata.status if metadata else "active",
                "created_at": metadata.created_at.isoformat() if metadata and metadata.created_at else None,
                "last_refreshed_at": metadata.last_refreshed_at.isoformat() if metadata and metadata.last_refreshed_at else None,
                "is_stale": metadata.is_stale if metadata else False,
                "staleness_hours": metadata.staleness_hours if metadata else None,
                "needs_refresh": metadata.needs_refresh if metadata else False,
                "auto_refresh_enabled": metadata.auto_refresh_enabled if metadata else True,
                "refresh_interval_hours": metadata.refresh_interval_hours if metadata else 24
            }

            return status

        except Exception as e:
            logger.error(f"Failed to get status for view '{view_name}': {e}")
            raise

    async def refresh_view(self, view_name: str) -> Dict[str, Any]:
        """
        Refresh a materialized view

        Args:
            view_name: Name of the view to refresh

        Returns:
            Refresh result with timing and metadata
        """
        start_time = datetime.now()

        try:
            logger.info(f"Refreshing materialized view: {view_name}")

            # Update status to 'refreshing'
            await self._update_metadata(view_name, {"status": "refreshing"})

            # Execute REFRESH MATERIALIZED VIEW
            refresh_sql = f"REFRESH MATERIALIZED VIEW {self.SCHEMA_NAME}.{view_name}"
            await self.db_client.execute_query(refresh_sql)

            # Calculate refresh duration
            refresh_duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            # Get updated row count
            count_sql = f"SELECT COUNT(*) as count FROM {self.SCHEMA_NAME}.{view_name}"
            count_result = await self.db_client.execute_query(count_sql)
            row_count = count_result[0]['count'] if count_result else 0

            # Get size
            size_sql = f"""
                SELECT pg_total_relation_size('{self.SCHEMA_NAME}.{view_name}') as size_bytes
            """
            size_result = await self.db_client.execute_query(size_sql)
            size_bytes = size_result[0]['size_bytes'] if size_result else 0

            # Update metadata
            await self._update_metadata(view_name, {
                "status": "active",
                "last_refreshed_at": datetime.now(),
                "refresh_duration_ms": refresh_duration_ms,
                "row_count": row_count,
                "size_bytes": size_bytes,
                "is_stale": False,
                "staleness_hours": 0.0,
                "error_message": None
            })

            logger.info(
                f"✓ Refreshed view '{view_name}' in {refresh_duration_ms:.1f}ms "
                f"({row_count:,} rows)"
            )

            return {
                "view_name": view_name,
                "success": True,
                "refresh_duration_ms": refresh_duration_ms,
                "row_count": row_count,
                "size_bytes": size_bytes
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to refresh view '{view_name}': {error_msg}")

            # Update metadata with error
            await self._update_metadata(view_name, {
                "status": "failed",
                "error_message": error_msg
            })

            return {
                "view_name": view_name,
                "success": False,
                "error": error_msg
            }

    async def refresh_all_views(self) -> Dict[str, Any]:
        """
        Refresh all materialized views

        Returns:
            Summary of refresh operations
        """
        views_list = await self.list_views()

        results = []
        success_count = 0
        fail_count = 0

        for view in views_list:
            view_name = view['view_name']
            result = await self.refresh_view(view_name)

            if result['success']:
                success_count += 1
            else:
                fail_count += 1

            results.append(result)

        summary = {
            "total_views": len(views_list),
            "success": success_count,
            "failed": fail_count,
            "results": results
        }

        logger.info(
            f"Refreshed all views: {success_count} succeeded, {fail_count} failed"
        )

        return summary

    async def check_and_refresh_stale_views(self) -> Dict[str, Any]:
        """
        Check for stale views and refresh them

        Returns:
            Summary of refresh operations
        """
        # Get all views that need refresh
        stmt = select(MaterializedViewMetadata).where(
            MaterializedViewMetadata.auto_refresh_enabled == True
        )
        result = await self.session.execute(stmt)
        all_metadata = result.scalars().all()

        # Update staleness for all views
        await self._update_staleness_for_all(all_metadata)

        # Filter views that need refresh
        stale_views = [m for m in all_metadata if m.needs_refresh]

        if not stale_views:
            logger.info("No stale views found")
            return {
                "total_checked": len(all_metadata),
                "stale_views": 0,
                "refreshed": 0,
                "results": []
            }

        logger.info(f"Found {len(stale_views)} stale views to refresh")

        # Refresh each stale view
        results = []
        for metadata in stale_views:
            result = await self.refresh_view(metadata.view_name)
            results.append(result)

        success_count = sum(1 for r in results if r['success'])

        summary = {
            "total_checked": len(all_metadata),
            "stale_views": len(stale_views),
            "refreshed": success_count,
            "failed": len(stale_views) - success_count,
            "results": results
        }

        return summary

    # Private helper methods

    async def _update_metadata(self, view_name: str, updates: Dict[str, Any]):
        """
        Update metadata for a view

        Args:
            view_name: Name of the view
            updates: Dictionary of fields to update
        """
        try:
            # Get or create metadata
            stmt = select(MaterializedViewMetadata).where(
                MaterializedViewMetadata.view_name == view_name
            )
            result = await self.session.execute(stmt)
            metadata = result.scalar_one_or_none()

            if metadata is None:
                # Create new metadata
                metadata = MaterializedViewMetadata(view_name=view_name)
                self.session.add(metadata)

            # Apply updates
            for key, value in updates.items():
                setattr(metadata, key, value)

            await self.session.commit()

        except Exception as e:
            await self.session.rollback()
            logger.error(f"Failed to update metadata for '{view_name}': {e}")
            raise

    async def _update_staleness_for_all(self, metadata_list: List[MaterializedViewMetadata]):
        """
        Update staleness metrics for all views

        Args:
            metadata_list: List of view metadata objects
        """
        now = datetime.now()

        for metadata in metadata_list:
            if metadata.last_refreshed_at:
                staleness = now - metadata.last_refreshed_at
                metadata.staleness_hours = staleness.total_seconds() / 3600

                # Mark as stale if older than threshold
                metadata.is_stale = metadata.staleness_hours >= self.STALENESS_THRESHOLD_HOURS
            else:
                # Never refreshed
                metadata.staleness_hours = None
                metadata.is_stale = True

        await self.session.commit()

    async def close(self):
        """Close database connections"""
        await self.session.close()
