import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")
# HAPI FHIR database URL - used for FHIR data queries (patient demographics, conditions, etc.)
# Uses asyncpg driver for async PostgreSQL connections
HAPI_DB_URL = os.getenv("HAPI_DB_URL", "postgresql+asyncpg://hapi:hapi@localhost:5433/hapi")


class SQLonFHIRAdapter:
    def __init__(self, database_url: str | None = None):
        """
        Initialize SQL-on-FHIR adapter using shared database engine.

        Bug #11 (part 2) fix (Nov 11, 2025): Use LAZY initialization to ensure
        engine is bound to correct event loop. Engine is only created on first use,
        preventing "Future attached to different loop" errors.

        Args:
            database_url: DEPRECATED (kept for API compatibility, but ignored)
                         Engine is now obtained from get_hapi_engine() which manages
                         per-event-loop engines automatically.
        """
        # LAZY initialization: Don't create engine here, only on first use
        # This ensures engine is created in the correct event loop context
        self._engine = None
        self._async_session = None
        import logging

        logger = logging.getLogger(__name__)
        logger.info("[SQLonFHIRAdapter] Initialized (engine will be created on first use)")

    @property
    def engine(self):
        """Lazy engine getter - creates HAPI engine on first access in current event loop."""
        if self._engine is None:
            from app.database import get_hapi_engine
            import asyncio

            self._engine = get_hapi_engine()
            # Bug #11 Part 5 fix: Use get_running_loop() for async contexts
            try:
                loop_id = id(asyncio.get_running_loop())
            except RuntimeError:
                loop_id = id(asyncio.get_event_loop())
            import logging

            logger = logging.getLogger(__name__)
            logger.info(f"[SQLonFHIRAdapter] Created shared HAPI engine for event loop {loop_id}")
        return self._engine

    @property
    def async_session(self):
        """Lazy session factory getter - creates on first access in current event loop."""
        if self._async_session is None:
            from app.database import get_hapi_session_factory

            self._async_session = get_hapi_session_factory()
        return self._async_session

    async def execute_sql(self, sql: str, params: dict | list | None = None):
        """
        Execute SQL query with optional parameterized values

        Args:
            sql: SQL query string with :param or :1 style placeholders
            params: Dict of named parameters or list of positional parameters

        Returns:
            List of result rows as dictionaries

        Security:
            Uses SQLAlchemy parameterized queries to prevent SQL injection
        """
        import logging

        logger = logging.getLogger(__name__)

        # Log query details for debugging
        logger.debug(
            f"[SQLonFHIRAdapter] Executing query:"
            f"\n  SQL: {sql[:200]}..."
            f"\n  Params: {params}"
            f"\n  Has params: {bool(params)}"
            f"\n  Param count: {len(params) if params else 0}"
        )

        # VERY simple sandbox: only allow SELECT
        if not sql.strip().lower().startswith("select"):
            raise ValueError("Only SELECT queries are allowed in this sandbox")

        async with self.async_session() as session:
            if params:
                # SQLAlchemy text() with bound parameters
                result = await session.execute(text(sql), params)
            else:
                result = await session.execute(text(sql))
            rows = [dict(row._mapping) for row in result]

        logger.debug(f"[SQLonFHIRAdapter] Query returned {len(rows)} rows")
        return rows
