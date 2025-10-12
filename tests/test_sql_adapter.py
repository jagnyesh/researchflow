import asyncio

from app.adapters.sql_on_fhir import SQLonFHIRAdapter


async def _create_table_and_query(adapter: SQLonFHIRAdapter):
    async with adapter.engine.begin() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS patient "
            "(id INTEGER PRIMARY KEY, name TEXT)"
        )
        await conn.execute(
            "INSERT INTO patient (name) VALUES ('Alice'), ('Bob')"
        )
    rows = await adapter.execute_sql("SELECT id, name FROM patient")
    return rows


def test_sql_adapter_sqlite(tmp_path):
    dbfile = tmp_path / "d.db"
    url = f"sqlite+aiosqlite:///{dbfile}"
    adapter = SQLonFHIRAdapter(database_url=url)
    rows = asyncio.get_event_loop().run_until_complete(
        _create_table_and_query(adapter)
    )
    assert len(rows) >= 2
