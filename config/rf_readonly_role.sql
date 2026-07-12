-- rf_readonly — scoped read-only identity for LLM-synthesized exploratory SQL
-- (Sprint 6.7 #92, ADR 0028 deployment note).
--
-- The exploratory portal's synthesis path executes LLM-authored SQL. This role
-- can SELECT the sqlonfhir analytics views and NOTHING else — no writes, no DDL,
-- and no access to the raw hfj_resource PHI JSONs in schema public. It is the
-- execution identity behind EXPLORATORY_DB_URL.
--
-- Idempotent: safe to run repeatedly. Mounted into the hapi-db container's
-- /docker-entrypoint-initdb.d (runs on a fresh volume); re-apply to an existing
-- database with:  psql "$HAPI_DB_URL" -f config/rf_readonly_role.sql
--
-- The sqlonfhir views are materialized AFTER container init by
-- scripts/materialize_views.py, so the SELECT grant is applied two ways:
--   1. GRANT SELECT ON ALL TABLES — covers any views that already exist.
--   2. ALTER DEFAULT PRIVILEGES — covers views/MVs created LATER by role hapi.
-- Postgres "TABLES" default-privilege class covers tables, views AND
-- materialized views, so both the custom-path MVs and the sqlonfhir-engine
-- tables are captured.
--
-- Dev-default password matches the repo's docker convention (hapi/hapi,
-- researchflow/researchflow). Production overrides via EXPLORATORY_DB_URL with
-- a real credential; this file is never the production secret.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rf_readonly') THEN
        CREATE ROLE rf_readonly LOGIN PASSWORD 'rf_readonly';  -- pragma: allowlist secret
    END IF;
END
$$;

-- Schema may not exist yet on a fresh volume (materialize_views.py creates it).
CREATE SCHEMA IF NOT EXISTS sqlonfhir;

GRANT USAGE ON SCHEMA sqlonfhir TO rf_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA sqlonfhir TO rf_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE hapi IN SCHEMA sqlonfhir
    GRANT SELECT ON TABLES TO rf_readonly;

-- Defence in depth: strip any PUBLIC-inherited write/usage on schema public so
-- the raw hfj_resource PHI tables are unreachable from this role. (Base tables
-- grant nothing to PUBLIC by default, but be explicit.)
REVOKE CREATE ON SCHEMA public FROM rf_readonly;
