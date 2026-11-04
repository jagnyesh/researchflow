"""Gate telemetry: what the human approval gates catch, and how fast (#144).

Read-only over the existing `approvals` table. G1 is requirements review, G2
phenotype-SQL review; the other approval types are reported under their own
names. Output is aggregate only: review notes can quote a request, so they are
classified here and never returned.
"""

import re
import statistics
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select

GATE_NAMES = {"requirements": "G1", "phenotype_sql": "G2"}
DECISIONS = ("approved", "rejected", "modified", "pending")

# Fixed taxonomy (≤8) for what a rejection or modification caught. First match
# wins, so the more specific patterns come first.
_CATEGORY_RULES = [
    ("phi_concern", r"\b(phi|pii|identif\w*|names?|ssn|mrn|de-?identif\w*|privacy)\b"),
    ("wrong_codes", r"\b(code|codes|icd|icd-?10|snomed|loinc|rxnorm|cpt)\b"),
    ("missing_predicate", r"\b(missing|forgot|omit\w*|drops?|dropped|without the)\b"),
    (
        "extra_predicate",
        r"\b(extra|unrequested|nobody asked|not asked|too narrow|over-?restrict\w*)\b",
    ),
    ("scope_creep", r"\b(scope|irb|beyond|out of scope)\b"),
    ("infeasible_cohort", r"\b(infeasible|feasib\w*|too small|too few|empty cohort|no patients)\b"),
]
CATEGORIES = tuple(name for name, _ in _CATEGORY_RULES) + ("other",)


def categorize_rejection(notes: Optional[str]) -> str:
    """One CATEGORIES label for a rejection/modification note."""
    text = (notes or "").lower()
    for name, pattern in _CATEGORY_RULES:
        if re.search(pattern, text):
            return name
    return "other"


def _gate(approval_type: str) -> str:
    return GATE_NAMES.get(approval_type, approval_type)


def summarize_gates(rows: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    """Per-gate counts, rejection rate, reviewer minutes and rejection categories.

    `rows` need approval_type, status, submitted_at, reviewed_at, review_notes.
    """
    # G1/G2 always appear: a gate that recorded nothing is itself a finding.
    by_gate: Dict[str, List[Any]] = {gate: [] for gate in GATE_NAMES.values()}
    for row in rows:
        by_gate.setdefault(_gate(row.approval_type), []).append(row)

    summary = {}
    for gate, gate_rows in sorted(by_gate.items()):
        counts = Counter(r.status for r in gate_rows if r.status in DECISIONS)
        decided = [r for r in gate_rows if r.status != "pending"]
        timed = [
            (r.reviewed_at - r.submitted_at).total_seconds() / 60
            for r in decided
            if r.reviewed_at is not None and r.submitted_at is not None
        ]
        caught = Counter(
            categorize_rejection(r.review_notes)
            for r in gate_rows
            if r.status in ("rejected", "modified")
        )
        summary[gate] = {
            "counts": {d: counts.get(d, 0) for d in DECISIONS},
            "rejection_rate": (counts["rejected"] / len(decided)) if decided else None,
            "reviewer_minutes": {
                "median": statistics.median(timed) if timed else None,
                "n": len(timed),
                "decided_without_timestamp": len(decided) - len(timed),
            },
            "categories": {c: caught.get(c, 0) for c in CATEGORIES},
        }
    return summary


async def load_gate_telemetry(request_ids: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """summarize_gates over the approvals table, optionally limited to some requests."""
    from app.database import get_db_session
    from app.database.models import Approval

    query = select(
        Approval.approval_type,
        Approval.status,
        Approval.submitted_at,
        Approval.reviewed_at,
        Approval.review_notes,
    )
    if request_ids is not None:
        query = query.where(Approval.request_id.in_(request_ids))
    async with get_db_session() as session:
        rows = (await session.execute(query)).all()
    return summarize_gates(rows)


def gate_telemetry_rows(summary: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One flat row per gate, for a dashboard table."""
    rows = []
    for gate, s in summary.items():
        caught = {k: v for k, v in s["categories"].items() if v}
        rows.append(
            {
                "gate": gate,
                **s["counts"],
                "rejection rate": s["rejection_rate"],
                "median reviewer minutes": s["reviewer_minutes"]["median"],
                "decided without timestamp": s["reviewer_minutes"]["decided_without_timestamp"],
                "top category": max(caught, key=caught.get) if caught else None,
            }
        )
    return rows
