"""
ResearchFlow Database Models

Data models for request tracking, agent execution, and workflow state.
"""

import os
import asyncio
from threading import local
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from .models import (
    Base,
    ResearchRequest,
    RequirementsData,
    FeasibilityReport,
    AgentExecution,
    Escalation,
    DataDelivery,
    AuditLog,
    Approval,
)

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")
HAPI_DB_URL = os.getenv("HAPI_DB_URL", "postgresql+asyncpg://hapi:hapi@localhost:5433/hapi")

# Thread-local storage for per-event-loop engines
_thread_local = local()


def get_engine():
    """
    Get or create async engine for current event loop.

    This ensures that each event loop gets its own engine, preventing
    'Queue is bound to a different event loop' errors in Streamlit and
    other multi-event-loop environments.

    Bug #11 Part 4 fix (Nov 11, 2025): Use get_running_loop() for async contexts
    to ensure we get the CURRENTLY RUNNING loop, not the default loop.

    Returns:
        AsyncEngine: Engine bound to current event loop
    """
    # Get current event loop
    # Try get_running_loop() first (for async contexts), fall back to get_event_loop() (for sync contexts)
    try:
        loop = asyncio.get_running_loop()  # Preferred: works from async functions
    except RuntimeError:
        # Not in async context, use get_event_loop() (sync contexts)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No event loop in current thread, create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

    loop_id = id(loop)

    # Initialize engines dict if not exists
    if not hasattr(_thread_local, "engines"):
        _thread_local.engines = {}

    # Create engine for this loop if not exists
    if loop_id not in _thread_local.engines:
        # Bug #12 fix v2 (Nov 11, 2025): Use small pool with proper configuration
        # to prevent both connection reuse issues AND connection exhaustion
        _thread_local.engines[loop_id] = create_async_engine(
            DATABASE_URL,
            echo=False,
            future=True,
            pool_size=5,  # Small pool to limit concurrent connections
            max_overflow=10,  # Allow burst up to 15 connections
            pool_pre_ping=True,  # Verify connections before use
            pool_recycle=3600,  # Recycle connections after 1 hour
        )

    return _thread_local.engines[loop_id]


def get_session_factory():
    """
    Get session factory for current event loop.

    Returns:
        sessionmaker: Session factory bound to current event loop's engine
    """
    engine = get_engine()
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def get_hapi_engine():
    """
    Get or create async engine for HAPI FHIR database for current event loop.

    This ensures that each event loop gets its own engine, preventing
    'Queue is bound to a different event loop' errors in Streamlit and
    other multi-event-loop environments.

    Bug #11 Part 4 fix (Nov 11, 2025): Use get_running_loop() for async contexts
    to ensure we get the CURRENTLY RUNNING loop, not the default loop.

    Returns:
        AsyncEngine: HAPI database engine bound to current event loop
    """
    # Get current event loop
    # Try get_running_loop() first (for async contexts), fall back to get_event_loop() (for sync contexts)
    try:
        loop = asyncio.get_running_loop()  # Preferred: works from async functions
    except RuntimeError:
        # Not in async context, use get_event_loop() (sync contexts)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No event loop in current thread, create one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

    loop_id = id(loop)

    # Initialize hapi_engines dict if not exists
    if not hasattr(_thread_local, "hapi_engines"):
        _thread_local.hapi_engines = {}

    # Create engine for this loop if not exists
    if loop_id not in _thread_local.hapi_engines:
        # Bug #12 fix v2 (Nov 11, 2025): Use small pool with proper configuration
        # to prevent both connection reuse issues AND connection exhaustion
        _thread_local.hapi_engines[loop_id] = create_async_engine(
            HAPI_DB_URL,
            echo=False,
            future=True,
            pool_size=5,  # Small pool to limit concurrent connections
            max_overflow=10,  # Allow burst up to 15 connections
            pool_pre_ping=True,  # Verify connections before use
            pool_recycle=3600,  # Recycle connections after 1 hour
        )

    return _thread_local.hapi_engines[loop_id]


def get_hapi_session_factory():
    """
    Get session factory for HAPI FHIR database for current event loop.

    Returns:
        sessionmaker: Session factory bound to current event loop's HAPI engine
    """
    engine = get_hapi_engine()
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def reset_engine():
    """
    Force reset of engine for current event loop.

    Bug #11 Part 4 fix (Nov 11, 2025): Use get_running_loop() for async contexts
    to ensure we get the CURRENTLY RUNNING loop, not the default loop.

    Useful for testing or when you need to ensure a fresh connection.
    """
    try:
        # Try get_running_loop() first (for async contexts), fall back to get_event_loop() (for sync contexts)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        loop_id = id(loop)

        if hasattr(_thread_local, "engines") and loop_id in _thread_local.engines:
            # Close existing engine
            # Note: We don't await dispose() here as this is a sync function
            # The engine will be garbage collected
            del _thread_local.engines[loop_id]
    except RuntimeError:
        pass  # No event loop, nothing to reset


# Database session context manager
@asynccontextmanager
async def get_db_session():
    """
    Provide a transactional scope around a series of operations.

    Automatically uses the engine bound to the current event loop,
    preventing 'Queue is bound to a different event loop' errors.

    Usage:
        async with get_db_session() as session:
            request = await session.get(ResearchRequest, request_id)
            await session.commit()
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Database initialization
async def init_db():
    """Create all tables in the database"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db():
    """Drop all tables in the database (for testing)"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


__all__ = [
    "Base",
    "ResearchRequest",
    "RequirementsData",
    "FeasibilityReport",
    "AgentExecution",
    "Escalation",
    "DataDelivery",
    "AuditLog",
    "Approval",
    "get_db_session",
    "init_db",
    "drop_db",
    "get_engine",
    "get_session_factory",
    "get_hapi_engine",
    "get_hapi_session_factory",
    "reset_engine",
]
