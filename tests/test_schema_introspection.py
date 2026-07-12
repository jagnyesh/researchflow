"""Sprint 6.7 #94 — live schema introspection: pg_catalog is the single source
of truth for what the LLM is told and (in #95) what the validator checks.

pg_catalog, NOT information_schema: the 4 custom-path MVs (relkind='m') do not
appear in information_schema.columns — discovered during #91 (PR #102).

Kills the #76 drift class: no more hand-maintained schema copies
(QueryInterpreter.AVAILABLE_VIEW_DEFINITIONS, #91's stub block).
"""

import pytest

from app.services.schema_introspection import (
    SchemaIntrospectionError,
    ViewSchema,
    introspect_schema,
    render_schema_block,
)
from app.services.sql_validator import ALLOWED_VIEWS


class TestRenderSchemaBlock:
    def _canned(self):
        from app.services.schema_introspection import ColumnInfo

        return {
            "patient_demographics": ViewSchema(
                name="patient_demographics",
                description="Core demographic information for patients",
                columns=(
                    ColumnInfo("patient_id", "text"),
                    ColumnInfo("gender", "text"),
                    ColumnInfo("birth_date", "text"),
                ),
            ),
            "condition_simple": ViewSchema(
                name="condition_simple",
                description="Simplified condition view",
                columns=(
                    ColumnInfo("patient_id", "text"),
                    ColumnInfo("snomed_display", "text"),
                ),
            ),
        }

    def test_block_lists_every_view_column_and_type(self):
        from app.services.schema_introspection import render_schema_block

        block = render_schema_block(self._canned())

        assert "sqlonfhir.patient_demographics" in block
        assert "birth_date text" in block
        assert "snomed_display text" in block
        assert "Core demographic information" in block

    def test_block_renders_views_deterministically_sorted(self):
        # Cache stability: same schema -> byte-identical block (prompt caching
        # keys on exact content).
        from app.services.schema_introspection import render_schema_block

        a = render_schema_block(self._canned())
        b = render_schema_block(dict(reversed(list(self._canned().items()))))

        assert a == b


@pytest.mark.requires_services
class TestLiveIntrospection:
    async def test_returns_all_seven_views_with_columns_and_types(self):
        from app.clients.hapi_db_client import HAPIDBClient
        import os

        db = HAPIDBClient(os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi"))
        schemas = await introspect_schema(db)

        assert set(schemas.keys()) == set(ALLOWED_VIEWS)
        for view in schemas.values():
            assert isinstance(view, ViewSchema)
            assert len(view.columns) > 0, f"{view.name} introspected zero columns"

        # The #91 wart that motivated live introspection: birth_date is TEXT.
        demo_cols = {c.name: c.pg_type for c in schemas["patient_demographics"].columns}
        assert demo_cols["birth_date"] == "text"
        # MV-only view (absent from information_schema) must be covered.
        cond_cols = {c.name for c in schemas["condition_simple"].columns}
        assert "snomed_display" in cond_cols

    async def test_descriptions_enriched_from_view_def_jsons(self):
        from app.clients.hapi_db_client import HAPIDBClient
        import os

        db = HAPIDBClient(os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi"))
        schemas = await introspect_schema(db)

        assert "demographic" in schemas["patient_demographics"].description.lower()

    async def test_missing_expected_view_raises_never_silently_omits(self):
        from app.clients.hapi_db_client import HAPIDBClient
        import os

        db = HAPIDBClient(os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi"))
        with pytest.raises(SchemaIntrospectionError, match="no_such_view"):
            await introspect_schema(
                db, view_names=frozenset({"patient_demographics", "no_such_view"})
            )

    async def test_live_system_prompt_clears_synthesis_models_caching_threshold(self):
        # #94 acceptance: threshold asserted, not assumed — and derived from
        # the model the synthesis call site actually uses (Sonnet 1024 vs
        # Haiku 4096; switching SYNTHESIS_MODEL to Haiku makes this test
        # demand 4096 automatically). Measured with tiktoken cl100k_base;
        # Sprint 8.2 found Anthropic counts ~13% HIGHER than tiktoken (5185
        # tiktoken -> 5850 Anthropic), so tiktoken >= threshold is conservative.
        import os
        import tiktoken

        from app.clients.hapi_db_client import HAPIDBClient
        from app.services.sql_synthesis import SYNTHESIS_MODEL, _build_system_prompt
        from app.utils.llm_client import _ANTHROPIC_CACHE_THRESHOLDS

        family = "haiku" if "haiku" in SYNTHESIS_MODEL else "sonnet"
        threshold = _ANTHROPIC_CACHE_THRESHOLDS[family]

        db = HAPIDBClient(os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi"))
        schemas = await introspect_schema(db)
        prompt = _build_system_prompt(render_schema_block(schemas))

        tokens = len(tiktoken.get_encoding("cl100k_base").encode(prompt))
        assert tokens >= threshold, (
            f"live schema prompt is {tokens} tiktoken tokens — below "
            f"{SYNTHESIS_MODEL}'s {threshold}-token caching threshold; "
            f"cache_control would be a silent no-op"
        )
