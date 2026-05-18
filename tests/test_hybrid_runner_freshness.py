"""Tests for FreshnessAnnotation enum + HybridRunner routing + metrics
emission + LangSmith tags.

Sprint 6.5 Phase 2A (#69). 8 TDD cycles, each one RED-GREEN-COMMIT. Each
test name maps 1:1 to the cycle name in issue #69's acceptance criteria.

These tests cover the core HybridRunner extension. Agent wiring is
Phase 2B (#70) — these tests do NOT exercise phenotype_agent or
extraction_agent. They drive HybridRunner directly via test fixtures.
"""

from __future__ import annotations

from app.sql_on_fhir.runner.freshness import FreshnessAnnotation


class TestFreshnessAnnotation:
    """Cycle 1: enum locks the three routing modes."""

    def test_freshness_annotation_enum_has_three_values(self):
        """Sprint 6.5 routes HybridRunner reads on FreshnessAnnotation.

        Three modes are the load-bearing architectural claim — they map
        to researcher-facing portals (EXPLORATORY ↔ :8501 Exploratory
        Portal, FORMAL_* ↔ :8502 Formal Portal) AND expose the
        pre/post-approval split inside the Formal Portal workflow.
        """
        values = {member.name for member in FreshnessAnnotation}
        assert values == {"EXPLORATORY", "FORMAL_DRAFT", "FORMAL_EXTRACTION"}
