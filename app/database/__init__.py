"""
ResearchFlow Database Models

Data models for request tracking, agent execution, and workflow state.
"""

import os
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
    Approval
)

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True
)

# Create session factory
async_session_factory = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


# Database session context manager
@asynccontextmanager
async def get_db_session():
    """
    Provide a transactional scope around a series of operations.

    Usage:
        async with get_db_session() as session:
            request = await session.get(ResearchRequest, request_id)
            await session.commit()
    """
    async with async_session_factory() as session:
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db():
    """Drop all tables in the database (for testing)"""
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
    "engine"
]
