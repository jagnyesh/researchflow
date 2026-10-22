"""A real driver error carrying a row value stays out of the logs (#183).

asyncpg puts offending values into its messages ("invalid input syntax for
type integer: \"<value>\"" — the #39 shape). Drives HAPIDBClient against real
Postgres; the value is computed at runtime, so it reaches the error only via
the driver, exactly like a stored row would.
"""

import logging
import os

import pytest

pytestmark = pytest.mark.requires_services

PHI_NEEDLE = "ALICE-ZZ-4410"


@pytest.mark.asyncio
async def test_driver_error_value_is_not_logged(caplog):
    from app.clients.hapi_db_client import HAPIDBClient

    client = HAPIDBClient(
        connection_url=os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi"),
        min_pool_size=1,
        max_pool_size=1,
    )
    await client.connect()
    try:
        with caplog.at_level(logging.DEBUG), pytest.raises(Exception) as raised:
            await client.execute_query(
                "SELECT x::int FROM (SELECT 'ALICE-' || $1 AS x) s", ["ZZ-4410"]
            )
    finally:
        await client.close()

    assert PHI_NEEDLE in str(raised.value), "precondition: the driver message carries the value"
    assert PHI_NEEDLE not in caplog.text
    assert "ref=" in caplog.text
