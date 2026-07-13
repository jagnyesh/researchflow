"""
Feasibility Service

Estimates cohort sizes for the exploratory portal by synthesizing a SELECT-only
COUNT query from the researcher's natural-language question (Sprint 6.7, ADR 0028):

    NL -> SQLSynthesizer -> SQLValidator (default-deny) -> execute -> scalar count

The legacy rule-based path (JoinQueryBuilder + QueryInterpreter's QueryIntent) was
retired in #100 once the synthesis path cleared its gate (#99). Synthesis is now the
only path. Execution runs through the scoped read-only rf_readonly role (#92) — no
PHI exposure: aggregate COUNT only, enforced by the validator.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from langsmith import traceable

from app.clients.hapi_db_client import HAPIDBClient
from app.services.schema_introspection import get_cached_schemas
from app.services.sql_synthesis import SQLSynthesizer, SynthesisError
from app.services.sql_validator import SQLValidator

logger = logging.getLogger(__name__)


class FeasibilityService:
    """Synthesize + validate + execute a COUNT query for a NL cohort question."""

    def __init__(self):
        hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")
        # Sprint 6.7 #92: synthesized SQL executes through the scoped read-only
        # rf_readonly role (SELECT on sqlonfhir only — no writes, no raw
        # hfj_resource PHI). Falls back to HAPI_DB_URL when EXPLORATORY_DB_URL is
        # unset so dev/test without the role still work.
        self.exploratory_db_client = HAPIDBClient(os.getenv("EXPLORATORY_DB_URL") or hapi_db_url)
        # Fail-closed guard: synthesis is now the ONLY path (#100), so a production
        # deploy MUST set EXPLORATORY_DB_URL — otherwise synthesized SQL would run
        # under HAPI's full-privilege credentials, defeating the rf_readonly
        # boundary (#92). Hard-fail in production, warn in dev/test (mirrors the
        # encryption-key startup gate + audit default-deny).
        if not os.getenv("EXPLORATORY_DB_URL"):
            msg = (
                "EXPLORATORY_DB_URL is unset — synthesized SQL would execute under "
                "HAPI's full-privilege credentials, defeating the rf_readonly "
                "read-only boundary (#92)."
            )
            if os.getenv("ENVIRONMENT", "").lower() == "production":
                raise RuntimeError(msg)
            logger.warning("%s Falling back to HAPI_DB_URL (dev/test only).", msg)

    @traceable(tags=["feasibility-service", "cohort-estimation", "portal:exploratory"])
    async def execute_feasibility_check(
        self,
        query_intent: Optional[Dict[str, Any]] = None,
        natural_language_query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Estimate cohort size by synthesizing SQL from the NL question.

        Args:
            query_intent: Vestigial after #100 — only ``time_period`` is read
                (the notebook has no UI source for it, so it is typically ``{}``).
            natural_language_query: The researcher's original question. Required —
                there is no legacy fallback. Absent/empty returns the honest-error
                variant, never a fabricated cohort (the #76 lesson).

        Returns:
            Success: ``{"status": "ok", "estimated_cohort": int, ...}``.
            Failure: the ``{"status": "error", ...}`` variant with NO numeric
            ``estimated_cohort`` key (#96/#97).
        """
        qi = query_intent or {}
        if not natural_language_query:
            return self._honest_error(
                explanation="No query text was provided.",
                rejected_sql="",
                reason="empty natural_language_query",
                query_intent=qi,
            )
        return await self._execute_via_llm_synthesis(natural_language_query, qi)

    async def _execute_via_llm_synthesis(
        self, natural_language_query: str, query_intent: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Sprint 6.7 #91+#95+#96: synthesize -> validate -> execute, with ONE
        feedback retry on validator rejection and an honest-error variant on
        any failure.

        The invariant (#76 lesson): a failure NEVER returns a numeric cohort.
        Validator rejection -> one resynthesis with the violations appended ->
        still invalid -> error variant. Execution error -> error variant
        immediately, no retry (a post-validation execution failure is
        structural; retrying just burns tokens to mask it).
        """
        # #92: everything on the synthesis path — introspection, EXPLAIN, and
        # execution — runs through the scoped read-only rf_readonly client.
        db = self.exploratory_db_client
        synthesizer = SQLSynthesizer(db_client=db)

        # The synthesis stage (introspection + one or two LLM calls) can fail
        # in ways that aren't validator rejections: the model declines / returns
        # non-JSON (SynthesisError), the LLM API errors, or introspection fails.
        # ALL of these become the honest-error card, never an uncaught traceback
        # on the researcher's screen (#97; #96 review Finding 3).
        try:
            # Schemas come from the SAME cached introspection the prompt was
            # built from, so prompt and validator can never diverge (#95).
            schemas = await get_cached_schemas(db)
            validator = SQLValidator(schemas=schemas)

            synthesis = await synthesizer.synthesize(natural_language_query)
            validation = validator.validate(synthesis.sql)
            if not validation.valid:
                logger.info("Synthesized SQL rejected; retrying once with feedback")
                feedback = self._format_feedback(synthesis.sql, validation.violations)
                synthesis = await synthesizer.synthesize(natural_language_query, feedback=feedback)
                validation = validator.validate(synthesis.sql)
                if not validation.valid:
                    logger.warning(
                        "Synthesized SQL rejected after retry: %s", validation.violations
                    )
                    return self._honest_error(
                        explanation=synthesis.explanation,
                        rejected_sql=synthesis.sql,
                        reason="; ".join(validation.violations),
                        query_intent=query_intent,
                    )
        except SynthesisError as e:
            logger.info("Synthesis produced no usable SQL: %s", e)
            return self._honest_error(
                explanation="The model could not turn this request into a valid query.",
                rejected_sql="",
                reason=str(e),
                query_intent=query_intent,
            )
        except Exception as e:
            # exc_info so a masked programming error (e.g. API drift) stays
            # discoverable in logs even though the user sees a generic card.
            logger.warning("Synthesis stage failed unexpectedly: %s", e, exc_info=True)
            return self._honest_error(
                explanation="This request could not be processed.",
                rejected_sql="",
                reason=f"synthesis stage failed ({type(e).__name__})",
                query_intent=query_intent,
            )

        # EXPLAIN dry-run (rule 8) + real execution — any DB failure here is an
        # immediate honest error, no retry.
        try:
            explain = await validator.validate_with_explain(synthesis.sql, db)
            if not explain.valid:
                return self._honest_error(
                    explanation=synthesis.explanation,
                    rejected_sql=validation.safe_sql,
                    reason="; ".join(explain.violations),
                    query_intent=query_intent,
                )
            start_time = datetime.now()
            rows = await db.execute_query(validation.safe_sql, timeout=5.0)
            execution_time_ms = (datetime.now() - start_time).total_seconds() * 1000
            estimated_cohort = self._extract_scalar_count(rows)
        except Exception as e:
            # NEVER interpolate the exception into the user-facing reason — a
            # value-bearing Postgres error (e.g. "invalid input syntax for
            # integer: 'Alice Smith'") would leak a raw column value into an
            # unauthenticated UI field (#39). Type only; full detail to the log.
            # Mirrors the _extract_scalar_count hardening (#95).
            logger.warning("Execution of synthesized SQL failed: %s", e)
            return self._honest_error(
                explanation=synthesis.explanation,
                rejected_sql=validation.safe_sql,
                reason=f"query execution failed ({type(e).__name__})",
                query_intent=query_intent,
            )

        logger.info(
            "LLM-synthesized query returned %s (%.1fms)", estimated_cohort, execution_time_ms
        )

        # #97: disclose data freshness. The exploratory portal reads batch-only
        # MVs; surface the citation anchor (MAX refreshed_at across the views
        # this query touched) so "data as of <ts>" is explicit, not implicit.
        batch_anchor_ts = await self._batch_anchor_for(validation.touched_views)

        return {
            "status": "ok",
            "estimated_cohort": estimated_cohort,
            "cohort_counts_by_view": {},
            "data_availability": {},
            "feasibility_score": 1.0 if estimated_cohort > 0 else 0.0,
            "warnings": [],
            "recommendations": [],
            "time_period": query_intent.get("time_period", {}),
            "executed_at": datetime.now().isoformat(),
            # What actually ran (normalized safe_sql), not the raw LLM output.
            "generated_sql": validation.safe_sql,
            "filter_summary": synthesis.explanation,
            "execution_time_ms": execution_time_ms,
            "used_join_query": False,
            # "data as of" freshness disclosure (ISO string, or None if the
            # touched views have no refresh record).
            "batch_anchor_ts": batch_anchor_ts.isoformat() if batch_anchor_ts else None,
        }

    async def _batch_anchor_for(self, view_names: List[str]):
        """MAX(refreshed_at) across the touched views, via the existing Sprint
        6.5 HybridRunner helper (reused, not re-implemented). Best-effort: a
        missing metadata table or empty result yields None rather than failing
        the whole query — freshness disclosure must never block a valid count."""
        try:
            from app.sql_on_fhir.runner.hybrid_runner import HybridRunner

            runner = HybridRunner(db_client=self.exploratory_db_client)
            return await runner.get_batch_anchor_ts_for_views(view_names)
        except Exception as e:
            logger.warning("Could not resolve batch_anchor_ts for %s: %s", view_names, e)
            return None

    @staticmethod
    def _format_feedback(rejected_sql: str, violations: List[str]) -> str:
        bullet = "\n".join(f"- {v}" for v in violations)
        return f"Rejected SQL:\n{rejected_sql}\n\nValidator violations:\n{bullet}"

    @staticmethod
    def _honest_error(
        explanation: str,
        rejected_sql: str,
        reason: str,
        query_intent: Dict[str, Any],
    ) -> Dict[str, Any]:
        """The error variant (#96). Test-enforced invariant: NO numeric
        estimated_cohort key — a failure must never render as a cohort count
        (the #76 lesson). #97 renders this in the notebook UI."""
        return {
            "status": "error",
            "explanation": explanation,
            "rejected_sql": rejected_sql,
            "reason": reason,
            "time_period": query_intent.get("time_period", {}),
            "executed_at": datetime.now().isoformat(),
        }

    @staticmethod
    def _extract_scalar_count(rows: List[Dict[str, Any]]) -> int:
        """Tracer supports single-count results only: exactly one row with one
        numeric value. Anything else raises — never a fabricated number (#76).
        Breakdown (GROUP BY) result mapping lands with the UI work in #97.
        """
        if len(rows) != 1 or len(rows[0]) != 1:
            raise ValueError(
                f"synthesized query returned a non-scalar result "
                f"({len(rows)} rows x {len(rows[0]) if rows else 0} columns); "
                f"only single-count queries are supported in the #91 tracer"
            )
        value = next(iter(rows[0].values()))
        if not isinstance(value, int):
            # NEVER interpolate the value — a non-int here can be raw PHI (e.g.
            # a name leaked past validation); the error must not disclose it.
            raise ValueError(
                f"synthesized query returned a non-scalar result: expected an "
                f"integer count, got {type(value).__name__}"
            )
        return value

    async def close(self):
        """Close the read-only database client."""
        await self.exploratory_db_client.close()
