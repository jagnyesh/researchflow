import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")


class SQLonFHIRAdapter:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or DATABASE_URL
        self.engine = create_async_engine(self.database_url, echo=False)
        self.async_session = sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def execute_sql(self, sql: str):
        # VERY simple sandbox: only allow SELECT
        if not sql.strip().lower().startswith("select"):
            raise ValueError("Only SELECT queries are allowed in this sandbox")
        async with self.async_session() as session:
            result = await session.execute(text(sql))
            rows = [dict(row._mapping) for row in result]
            return rows
