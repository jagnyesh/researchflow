-- Materialized View row-count oracles (sprint-agnostic; git history encodes
-- when each query was added).
--
-- These queries replicate the WHERE clauses of the corresponding view-defs
-- so the count CAN be compared apples-to-apples with the sqlonfhir-emitted
-- table row count. The 1% gate from issue #40 measures actual MV row count
-- against the oracle defined here.
--
-- DO NOT compare an MV's row count against the raw resource count (e.g.,
-- count of all Conditions) — the view-def's WHERE clause filters them.
-- Sprint 6.3 D3 anchored 14,832 for condition_diagnoses but that was the
-- UNFILTERED count; the filtered oracle is much smaller (see below).
-- This file exists specifically to prevent future re-derivation of
-- "what should this MV's row count be?"

-- ============================================================================
-- condition_diagnoses
-- ============================================================================
-- View-def WHERE clause:
--   clinicalStatus.coding.code.where($this in
--     ('active' | 'recurrence' | 'relapse' | 'resolved' | 'remission')
--   ).exists()
--
-- Data observation (2026-05-15, Sprint 6.4 cycle 3 measurement against
-- HAPI :5433 Synthea load): the distinct clinicalStatus.coding.code
-- values present are 'active' (3,582 rows) and 'resolved' (11,250 rows).
-- The other three OR-set values ('recurrence', 'relapse', 'remission')
-- don't appear in the current Synthea corpus. So all 14,832 stored
-- Conditions pass the view-def's WHERE clause — the filter is effectively
-- a no-op against today's data but documents intent for future ingestion.
--
-- Meta-pattern note (per CLAUDE.md "Operating discipline"): an earlier
-- draft of this oracle only checked for 'active' and produced 3,582, off
-- by 4×. The 'resolved' status was discovered when actual sqlonfhir
-- output emitted 14,832 rows. Lesson: GROUP BY the column being
-- WHERE-clause-replicated before fixing the oracle, not just sample one
-- row of stored JSON.
--
-- Expected at sprint start 2026-05-15: 14,832 rows.
SELECT count(*) AS condition_diagnoses_oracle
FROM hfj_resource r
JOIN hfj_res_ver v ON v.res_id = r.res_id AND v.res_ver = r.res_ver
WHERE r.res_type = 'Condition'
  AND r.res_deleted_at IS NULL
  AND (
    v.res_text_vc::jsonb #> '{clinicalStatus,coding}' @> '[{"code":"active"}]'::jsonb
    OR v.res_text_vc::jsonb #> '{clinicalStatus,coding}' @> '[{"code":"recurrence"}]'::jsonb
    OR v.res_text_vc::jsonb #> '{clinicalStatus,coding}' @> '[{"code":"relapse"}]'::jsonb
    OR v.res_text_vc::jsonb #> '{clinicalStatus,coding}' @> '[{"code":"resolved"}]'::jsonb
    OR v.res_text_vc::jsonb #> '{clinicalStatus,coding}' @> '[{"code":"remission"}]'::jsonb
  );

-- ============================================================================
-- observation_labs + procedure_history oracles to be added in cycle 4.
-- ============================================================================
-- Cycle 4 implementer: the WHERE clauses for those view-defs are different
-- shapes (`category.coding.where(system=X and code=Y).exists()` for
-- observation_labs; `status in ('completed' | 'in-progress')` for
-- procedure_history). Replicate each WHERE in the same JSONB-containment
-- pattern; capture sprint-start counts in comments.
