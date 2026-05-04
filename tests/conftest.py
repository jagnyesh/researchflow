"""
Pytest configuration for test database isolation
"""

import os
import sys
import pytest
import asyncio
from sqlalchemy import text

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Set test database before importing app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"

from app.database import init_db, get_db_session, get_engine
from app.database.models import Base


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function", autouse=False)
async def clean_database():
    """Clean database before each test - call explicitly if needed"""
    # Initialize database with schema
    await init_db()

    # Clear all tables
    async with get_db_session() as session:
        await session.execute(text("DELETE FROM agent_executions"))
        await session.execute(text("DELETE FROM escalations"))
        await session.execute(text("DELETE FROM approvals"))
        await session.execute(text("DELETE FROM data_deliveries"))
        await session.execute(text("DELETE FROM requirements_data"))
        await session.execute(text("DELETE FROM feasibility_reports"))
        await session.execute(text("DELETE FROM research_requests"))
        await session.execute(text("DELETE FROM audit_logs"))
        await session.commit()

    yield


# Initialize database schema once at module level
@pytest.fixture(scope="session", autouse=True)
def init_test_db(event_loop):
    """Initialize test database schema once"""
    event_loop.run_until_complete(init_db())


@pytest.fixture(scope="session", autouse=True)
def session_audit_redis(event_loop):
    """Provide a default fakeredis client for the audit pipeline (Issue #2).

    Without this, the audit middleware fails-closed (5xx) on every PHI request
    because no audit Redis is configured. Tests that need their own fakeredis
    instance (e.g. to assert RPUSH content) override this with a function-scoped
    fixture that save/restores around it.
    """
    import fakeredis.aioredis
    from app.security import audit_middleware as am

    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    am.set_audit_redis(fake)
    yield fake
    am.set_audit_redis(None)
    event_loop.run_until_complete(fake.aclose())
