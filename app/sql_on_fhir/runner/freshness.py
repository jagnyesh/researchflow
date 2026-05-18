"""FreshnessAnnotation: how HybridRunner routes reads based on intent.

Sprint 6.5 (#67). Three modes map to researcher-facing portals AND expose
the pre/post-approval split inside the Formal Portal workflow:

- EXPLORATORY: Exploratory Portal queries (:8501 Text2SQL NL).
  Speed-merged — researcher is iterating; fresh data matters.
- FORMAL_DRAFT: Formal Portal cohort-estimation step (pre-approval
  HITL gate). Speed-merged with metadata — researcher may revise
  criteria; estimate should reflect today's data.
- FORMAL_EXTRACTION: Formal Portal post-approval extraction.
  Batch-only, citable via batch_anchor_ts — must be reproducible if
  audited; should match the approved-cohort snapshot.

Researcher approves a cohort *definition* (SQL/criteria), not a row-set.
The row-set materializes at extraction time against the current batch.

Full design rationale lives in
docs/decisions/0027-sprint-6-5-differential-freshness-routing.md
(committed at sprint close).
"""

from __future__ import annotations

from enum import Enum


class FreshnessAnnotation(Enum):
    """Routing mode passed to HybridRunner.execute(..., mode=...)."""

    EXPLORATORY = "exploratory"
    FORMAL_DRAFT = "formal_draft"
    FORMAL_EXTRACTION = "formal_extraction"
