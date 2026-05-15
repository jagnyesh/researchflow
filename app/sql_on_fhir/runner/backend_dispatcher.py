"""Sprint 6.4 — FHIRPath backend dispatcher.

Routes a view-def to its FHIRPath evaluation backend based on the
`runner_hint` field in the view-def JSON. Both the write path
(`scripts/materialize_views.py` via `ViewMaterializer`) and the read path
(`MaterializedViewRunner`) call `select_backend()` — single dispatch
source for the runner stack.

Default when `runner_hint` is missing: `"custom"`. This preserves backward
compatibility — every existing view-def JSON (the 4 currently-working MVs)
routes to the custom transpiler unchanged. New view-defs added in future
sprints should declare `runner_hint: "sqlonfhir"` explicitly; the
convention is documented in the Sprint 6.4 ADR.

See issue #40 (Sprint 6.4 pre-committed gate #5) and DECISIONS.md
"Sprint 6.3 — VERDICT REVISION 2026-05-14: GO sqlonfhir" for the
rationale behind the two-backend dispatch design.
"""

from __future__ import annotations

from typing import Any, Dict, Literal

Backend = Literal["custom", "sqlonfhir"]


def select_backend(view_def: Dict[str, Any]) -> Backend:
    """Route a view-def to its FHIRPath backend.

    Args:
        view_def: A view-def JSON dict (FHIR ViewDefinition resource).

    Returns:
        Either `"custom"` or `"sqlonfhir"`. Defaults to `"custom"` if the
        `runner_hint` field is absent — preserves backward compatibility
        for view-defs that pre-date Sprint 6.4.
    """
    hint = view_def.get("runner_hint", "custom")
    if hint == "sqlonfhir":
        return "sqlonfhir"
    return "custom"
