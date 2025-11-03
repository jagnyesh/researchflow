import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")


class SQLonFHIRAdapter:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or DATABASE_URL
        self.engine = create_async_engine(self.database_url, echo=False)
        self.async_session = sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

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
            return rows
