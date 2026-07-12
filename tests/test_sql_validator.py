"""Sprint 6.7 #91 — SQLValidator tracer: minimal default-deny gate for
LLM-synthesized exploratory SQL.

Tracer scope (ADR 0028 decision 4, minimal subset): sqlglot parse, exactly one
statement, SELECT-only, table refs restricted to the 7 sqlonfhir views. The
full 8-rule set (column existence, aggregate-only + dimension allowlist,
function allowlist, LIMIT/timeout, EXPLAIN dry-run) lands in #95.

Behavior under test: validate(sql) -> ValidationResult. Every rejection names
the rule it broke — #96's retry loop feeds that text back to the LLM.
"""

from app.services.sql_validator import SQLValidator


class TestSelectOnly:
    def test_rejects_delete_statement(self):
        result = SQLValidator().validate("DELETE FROM sqlonfhir.patient_demographics")

        assert result.valid is False
        assert any("SELECT" in v for v in result.violations)

    def test_accepts_valid_count_select_on_known_views(self):
        sql = """
            SELECT COUNT(DISTINCT p.patient_id)
            FROM sqlonfhir.patient_demographics p
            JOIN sqlonfhir.condition_simple c ON c.patient_id = p.patient_id
            WHERE p.gender = 'female'
        """
        result = SQLValidator().validate(sql)

        assert result.valid is True
        assert result.violations == []


class TestTableAllowlist:
    def test_rejects_unknown_view_in_sqlonfhir_schema(self):
        result = SQLValidator().validate("SELECT COUNT(*) FROM sqlonfhir.made_up_view")

        assert result.valid is False
        assert any("made_up_view" in v for v in result.violations)

    def test_rejects_raw_hapi_table_outside_sqlonfhir_schema(self):
        # public.hfj_resource holds raw FHIR JSONs (full PHI). The allowlist,
        # not just the read-only role (#92), must refuse it.
        result = SQLValidator().validate("SELECT COUNT(*) FROM public.hfj_resource")

        assert result.valid is False
        assert any("hfj_resource" in v for v in result.violations)

    def test_rejects_unqualified_table_reference(self):
        result = SQLValidator().validate("SELECT COUNT(*) FROM patient_demographics")

        assert result.valid is False
        assert any("patient_demographics" in v for v in result.violations)


class TestWriteMasquerades:
    def test_rejects_select_into_it_is_a_write(self):
        # Postgres SELECT INTO == CREATE TABLE AS; parses as exp.Select but writes.
        result = SQLValidator().validate(
            "SELECT * INTO sqlonfhir.patient_simple FROM sqlonfhir.patient_demographics"
        )

        assert result.valid is False
        assert any("INTO" in v for v in result.violations)

    def test_rejects_three_part_catalog_qualified_table(self):
        # otherdb.sqlonfhir.patient_demographics satisfies db+name checks unless
        # the catalog qualifier is inspected (postgres_fdw / foreign catalogs).
        result = SQLValidator().validate(
            "SELECT COUNT(*) FROM otherdb.sqlonfhir.patient_demographics"
        )

        assert result.valid is False
        assert any("otherdb" in v for v in result.violations)


class TestCTEViolationMessages:
    def test_cte_launder_rejected_by_naming_inner_table_not_alias(self):
        # CTE alias `x` must not be flagged (nonsense feedback for #96's retry
        # loop); the disallowed INNER table is the real violation.
        result = SQLValidator().validate(
            "WITH x AS (SELECT patient_id FROM public.hfj_resource) " "SELECT COUNT(*) FROM x"
        )

        assert result.valid is False
        assert any("hfj_resource" in v for v in result.violations)
        assert not any("'x'" in v for v in result.violations)


class TestSingleStatement:
    def test_rejects_stacked_statements(self):
        result = SQLValidator().validate(
            "SELECT COUNT(*) FROM sqlonfhir.patient_demographics; "
            "DROP TABLE sqlonfhir.patient_demographics"
        )

        assert result.valid is False
        assert any("one" in v for v in result.violations)

    def test_rejects_unparseable_sql(self):
        result = SQLValidator().validate("SELEKT frum WHERE ((")

        assert result.valid is False
        assert result.violations
