"""#438 against a real Postgres: a refresh that really fails must degrade health.

Runs on a throwaway cluster it starts itself (initdb + pg_ctl in a temp dir, a
free local port), so it never touches the live :5433 HAPI database. Skips when
the Postgres server binaries aren't installed.
"""

import glob
import os
import shutil
import socket
import subprocess

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import materialized_views as api
from app.clients.hapi_db_client import HAPIDBClient
from app.database.models import MaterializedViewMetadata
from app.services.materialized_view_service import MaterializedViewService


def _pg_bin(name):
    found = shutil.which(name)
    if found:
        return found
    for pattern in (
        f"/opt/homebrew/opt/postgresql*/bin/{name}",
        f"/usr/lib/postgresql/*/bin/{name}",
    ):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return None


@pytest.fixture(scope="module")
def pg_url(tmp_path_factory):
    initdb, pg_ctl = _pg_bin("initdb"), _pg_bin("pg_ctl")
    if not (initdb and pg_ctl) or os.geteuid() == 0:
        pytest.skip("Postgres server binaries unavailable (or running as root)")
    data = str(tmp_path_factory.mktemp("pgdata"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "LC_ALL": "C"}
    subprocess.run(
        [initdb, "-D", data, "-A", "trust", "-U", "t", "--locale=C"],
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        [
            pg_ctl,
            "-D",
            data,
            "-o",
            f"-p {port} -c unix_socket_directories= -c listen_addresses=127.0.0.1",
            "-w",
            "start",
        ],
        # DEVNULL, not capture_output: the server inherits the pipe and run() would wait on it.
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        yield f"postgresql://t@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run([pg_ctl, "-D", data, "-m", "immediate", "stop"], capture_output=True)


@pytest_asyncio.fixture
async def service(pg_url):
    client = HAPIDBClient(pg_url, min_pool_size=1, max_pool_size=2)
    await client.connect()
    await client.execute_query("CREATE SCHEMA IF NOT EXISTS sqlonfhir")
    engine = create_async_engine(pg_url.replace("postgresql://", "postgresql+asyncpg://"))
    async with engine.begin() as conn:
        await conn.run_sync(MaterializedViewMetadata.__table__.create, checkfirst=True)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    svc = MaterializedViewService(client, session)
    yield svc
    await session.close()
    await engine.dispose()
    await client.close()


@pytest.mark.asyncio
async def test_real_failed_refresh_makes_health_degraded(service, monkeypatch):
    for name in ("good_view", "bad_view"):
        await service.db_client.execute_query(
            f"CREATE MATERIALIZED VIEW IF NOT EXISTS sqlonfhir.{name} AS SELECT 1 AS id"
        )
    # CONCURRENTLY needs a unique index: good_view has one, bad_view doesn't,
    # so bad_view's refresh fails in Postgres itself.
    await service.db_client.execute_query(
        "CREATE UNIQUE INDEX IF NOT EXISTS good_view_id ON sqlonfhir.good_view (id)"
    )

    assert (await service.refresh_view("good_view"))["success"] is True
    assert (await service.refresh_view("bad_view"))["success"] is False

    async def fake_get_service():
        return service

    async def keep_open():
        pass

    monkeypatch.setattr(api, "get_service", fake_get_service)
    monkeypatch.setattr(service, "close", keep_open)

    out = await api.health_check()
    assert out["status"] == "degraded"
    assert out["failed_views"] == ["bad_view"]
