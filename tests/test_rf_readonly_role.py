"""Sprint 6.7 #92 — rf_readonly role permission boundary (ADR 0028 deployment note).

The exploratory synthesis path executes LLM-authored SQL under this role. It
must be able to SELECT the sqlonfhir analytics views (and read pg_catalog for
introspection) and NOTHING else: no writes, no DDL, no access to the raw
hfj_resource PHI JSONs.

Gated on the running HAPI :5433 with the role applied (config/rf_readonly_role.sql,
run by docker-compose initdb on a fresh volume; re-apply manually to an existing
one). Not in the base CI job until #93's docker-compose job lands.
"""

import os

import pytest

pytest.importorskip("asyncpg")
import asyncpg

RF_READONLY_URL = os.getenv(
    "EXPLORATORY_DB_URL", "postgresql://rf_readonly:rf_readonly@localhost:5433/hapi"
)


class TestFailClosedGuard:
    """#92 review ESCALATE-1 (unconditional after #100 — synthesis is the only
    path): EXPLORATORY_DB_URL unset would run synthesized SQL under HAPI's
    full-privilege creds, defeating the boundary. Hard-fail in production, warn
    in dev."""

    def test_production_hard_fails_when_url_unset(self, monkeypatch):
        from app.services.feasibility_service import FeasibilityService

        monkeypatch.delenv("EXPLORATORY_DB_URL", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")

        with pytest.raises(RuntimeError, match="EXPLORATORY_DB_URL"):
            FeasibilityService()

    def test_dev_warns_but_does_not_fail(self, monkeypatch):
        from app.services.feasibility_service import FeasibilityService

        monkeypatch.delenv("EXPLORATORY_DB_URL", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)

        # Constructs without raising (falls back to HAPI_DB_URL, dev only).
        fs = FeasibilityService()
        assert fs.exploratory_db_client is not None

    def test_url_set_never_guards(self, monkeypatch):
        from app.services.feasibility_service import FeasibilityService

        monkeypatch.setenv("EXPLORATORY_DB_URL", RF_READONLY_URL)
        monkeypatch.setenv("ENVIRONMENT", "production")

        # URL present in prod must NOT fail — the boundary is configured.
        FeasibilityService()


@pytest.mark.requires_services
class TestRfReadonlyBoundary:
    async def _connect(self):
        return await asyncpg.connect(RF_READONLY_URL)

    async def test_can_select_sqlonfhir_views(self):
        conn = await self._connect()
        try:
            n = await conn.fetchval("SELECT COUNT(*) FROM sqlonfhir.patient_demographics")
            assert n > 0
        finally:
            await conn.close()

    async def test_can_read_pg_catalog_for_introspection(self):
        # The synthesis prompt + validator column checks introspect pg_catalog;
        # rf_readonly must be able to.
        conn = await self._connect()
        try:
            n = await conn.fetchval(
                "SELECT count(*) FROM pg_catalog.pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'sqlonfhir'"
            )
            assert n >= 7
        finally:
            await conn.close()

    async def test_cannot_select_raw_hfj_resource_phi(self):
        conn = await self._connect()
        try:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.fetchval("SELECT COUNT(*) FROM public.hfj_resource")
        finally:
            await conn.close()

    async def test_cannot_insert(self):
        conn = await self._connect()
        try:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(
                    "INSERT INTO sqlonfhir.patient_demographics(patient_id) VALUES ('x')"
                )
        finally:
            await conn.close()

    async def test_cannot_create_ddl(self):
        conn = await self._connect()
        try:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute("CREATE TABLE sqlonfhir.evil (x int)")
        finally:
            await conn.close()
