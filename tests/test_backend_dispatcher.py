"""Sprint 6.4 — Backend dispatcher tests.

The dispatch primitive routes view-defs to their FHIRPath backend based on
the `runner_hint` field in the view-def JSON. Both the write path
(`scripts/materialize_views.py` via `ViewMaterializer`) and the read path
(`MaterializedViewRunner`) import this function — single dispatch source.

Per the Sprint 6.4 locked pre-committed gate (issue #40):

  Gate #5: Dispatch plumbing unit test passes.
    Asserts: view-def with `runner_hint: "sqlonfhir"` routes to sqlonfhir
    backend; view-def without the field (or with `"custom"`) routes to
    custom transpiler.

Backward compatibility: default for missing `runner_hint` is `"custom"`,
so every existing view-def JSON works unchanged.
"""

from __future__ import annotations

import pytest

from app.sql_on_fhir.runner.backend_dispatcher import Backend, select_backend


class TestSelectBackend:
    """Sprint 6.4 dispatch primitive — contract per issue #40 gate #5."""

    def test_explicit_sqlonfhir_hint_routes_to_sqlonfhir(self):
        """View-def with `runner_hint: "sqlonfhir"` → "sqlonfhir" backend."""
        view_def = {
            "resourceType": "ViewDefinition",
            "name": "procedure_history",
            "runner_hint": "sqlonfhir",
        }
        assert select_backend(view_def) == "sqlonfhir"

    def test_explicit_custom_hint_routes_to_custom(self):
        """View-def with `runner_hint: "custom"` → "custom" backend."""
        view_def = {
            "resourceType": "ViewDefinition",
            "name": "patient_simple",
            "runner_hint": "custom",
        }
        assert select_backend(view_def) == "custom"

    def test_missing_runner_hint_defaults_to_custom(self):
        """View-def without `runner_hint` → "custom" (backward compat).

        This is load-bearing for Sprint 6.4: every existing view-def JSON
        (the 4 currently-working MVs and any future legacy view-defs) must
        route to the custom transpiler unchanged. Forgetting this default
        would silently break the 4 working MVs the moment dispatch ships.
        """
        view_def = {
            "resourceType": "ViewDefinition",
            "name": "patient_demographics",
            # no runner_hint field
        }
        assert select_backend(view_def) == "custom"

    def test_return_type_is_literal_backend(self):
        """Return type is the `Backend` literal type, not raw str.

        Documents the public contract — callers can type-check against
        `Backend` instead of comparing to arbitrary strings.
        """
        view_def = {"resourceType": "ViewDefinition", "name": "x"}
        result: Backend = select_backend(view_def)
        # Both literal values must be acceptable assignments
        assert result in ("custom", "sqlonfhir")
