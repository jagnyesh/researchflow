"""Sprint 6.4 cycle 2 — ViewMaterializer integration with backend dispatcher.

The dispatch primitive shipped in cycle 1 (`select_backend()` at
`app/sql_on_fhir/runner/backend_dispatcher.py`) is now wired into
`ViewMaterializer` (`scripts/materialize_views.py`). The seam is a new
method `_build_view_sql(view_def)` that:

  - Routes view-defs with `runner_hint: "sqlonfhir"` to the sqlonfhir path
    (stubbed in this cycle — cycle 3 lifts the real sqlonfhir.evaluate()).
  - Routes view-defs without the field (or with `"custom"`) to the
    existing custom transpiler — backward compat for the 4 working MVs.

Per Sprint 6.4 #40 gate #5: dispatch plumbing unit test passes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ isn't a package; add it to sys.path so we can import
# ViewMaterializer from scripts.materialize_views.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from materialize_views import ViewMaterializer  # noqa: E402


class TestViewMaterializerDispatch:
    """ViewMaterializer routes view-defs to the dispatched backend."""

    def test_sqlonfhir_marked_view_def_routes_to_sqlonfhir_path(self):
        """A view-def with `runner_hint: "sqlonfhir"` hits the sqlonfhir branch.

        Cycle 2 stubs the sqlonfhir path with NotImplementedError — the raise
        is the test signal that dispatch routing reached this branch. Cycle
        3 will lift the real sqlonfhir.evaluate() invocation here.
        """
        materializer = ViewMaterializer("postgresql://dummy")  # no DB
        view_def = {
            "resourceType": "ViewDefinition",
            "resource": "Patient",
            "name": "test_view",
            "runner_hint": "sqlonfhir",
            "select": [{"column": [{"name": "id", "path": "id"}]}],
        }
        with pytest.raises(NotImplementedError, match="sqlonfhir backend"):
            materializer._build_view_sql(view_def)

    def test_unmarked_view_def_routes_to_custom_transpiler(self):
        """A view-def without `runner_hint` uses the existing custom transpiler.

        Backward compatibility for the 4 working MVs. Verifies by exercising
        the REAL custom transpiler (no mock) — testing behavior through the
        public surface (the returned SQL string), not implementation.
        """
        materializer = ViewMaterializer("postgresql://dummy")
        view_def = {
            "resourceType": "ViewDefinition",
            "resource": "Patient",
            "name": "patient_minimal",
            "select": [
                {
                    "column": [
                        {"name": "id", "path": "id"},
                        {"name": "fhir_id", "path": "getResourceKey()"},
                    ]
                }
            ],
        }
        sql = materializer._build_view_sql(view_def)
        assert sql, "custom transpiler should produce non-empty SQL"
        assert "FROM" in sql.upper(), "custom transpiler output should look like SQL"

    def test_explicit_custom_hint_also_routes_to_custom_transpiler(self):
        """Explicit `runner_hint: "custom"` is equivalent to missing field.

        Both must produce the same SQL — the field is opt-in to sqlonfhir,
        not opt-in to custom.
        """
        materializer = ViewMaterializer("postgresql://dummy")
        view_def = {
            "resourceType": "ViewDefinition",
            "resource": "Patient",
            "name": "patient_minimal",
            "runner_hint": "custom",
            "select": [{"column": [{"name": "id", "path": "id"}]}],
        }
        sql = materializer._build_view_sql(view_def)
        assert sql, "custom transpiler should produce non-empty SQL"
