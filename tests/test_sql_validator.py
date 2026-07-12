"""Sprint 6.7 #91 — SQLValidator tracer: minimal default-deny gate for
LLM-synthesized exploratory SQL.

Tracer scope (ADR 0028 decision 4, minimal subset): sqlglot parse, exactly one
statement, SELECT-only, table refs restricted to the 7 sqlonfhir views. The
full 8-rule set (column existence, aggregate-only + dimension allowlist,
function allowlist, LIMIT/timeout, EXPLAIN dry-run) lands in #95.

Behavior under test: validate(sql) -> ValidationResult. Every rejection names
the rule it broke — #96's retry loop feeds that text back to the LLM.
"""

from app.services.schema_introspection import ColumnInfo, ViewSchema
from app.services.sql_validator import SQLValidator

CANNED_SCHEMAS = {
    "patient_demographics": ViewSchema(
        name="patient_demographics",
        description="",
        columns=(
            ColumnInfo("patient_id", "text"),
            ColumnInfo("gender", "text"),
            ColumnInfo("birth_date", "text"),
            ColumnInfo("family_name", "text"),
            ColumnInfo("postal_code", "text"),
        ),
    ),
    "patient_simple": ViewSchema(
        name="patient_simple",
        description="",
        columns=(ColumnInfo("id", "text"), ColumnInfo("gender", "text")),
    ),
    "condition_simple": ViewSchema(
        name="condition_simple",
        description="",
        columns=(
            ColumnInfo("patient_id", "text"),
            ColumnInfo("code_text", "text"),
            ColumnInfo("snomed_display", "text"),
        ),
    ),
    "observation_labs": ViewSchema(
        name="observation_labs",
        description="",
        columns=(
            ColumnInfo("patient_id", "text"),
            ColumnInfo("code_display", "text"),
            ColumnInfo("value_quantity", "numeric"),
        ),
    ),
}


class TestValueAggregateExfiltration:
    """#95 review F1/F3 — 'is an aggregate' is NOT 'is safe'. Concatenating
    aggregates and value-aggregates over text columns exfiltrate raw PHI while
    passing a naive aggregate check. All must be rejected."""

    def test_rejects_string_agg_of_names(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT string_agg(family_name, ',') FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False

    def test_rejects_array_agg_of_names(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT array_agg(family_name) FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False

    def test_rejects_json_agg_of_names(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT json_agg(family_name) FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False

    def test_rejects_min_over_text_name_column(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT MIN(family_name) FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False

    def test_rejects_max_over_text_name_column(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT MAX(family_name) FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False

    def test_rejects_min_over_birth_date_the_dob_leak(self):
        # birth_date is TEXT in the MVs; MIN would surface a real patient DOB.
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT MIN(birth_date) FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False

    def test_rejects_name_walk_min_with_predicate(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT MIN(family_name) FROM sqlonfhir.patient_demographics "
            "WHERE family_name > 'Aaa'"
        )
        assert result.valid is False

    def test_accepts_avg_over_numeric_measure(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT AVG(value_quantity) FROM sqlonfhir.observation_labs"
        )
        assert result.valid is True, result.violations

    def test_accepts_min_max_over_numeric_measure(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT MIN(value_quantity), MAX(value_quantity) FROM sqlonfhir.observation_labs"
        )
        assert result.valid is True, result.violations


class TestSubqueryLaundering:
    """#95 re-review F8 — a FROM-clause derived table or CTE can relabel a PHI
    column (family_name AS gender) and launder it past both the dimension
    allowlist and the numeric-type check. The synthesis prompt bans CTEs and
    never uses FROM-subqueries, so both are rejected outright; WHERE-clause
    filter subqueries stay allowed."""

    def test_rejects_from_derived_table_relabeling_phi_as_dimension(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT sub.gender, COUNT(*) FROM "
            "(SELECT family_name AS gender FROM sqlonfhir.patient_demographics) sub "
            "GROUP BY sub.gender"
        )
        assert result.valid is False
        assert any("subquer" in v.lower() or "derived" in v.lower() for v in result.violations)

    def test_rejects_from_derived_table_value_aggregate_over_text(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT MIN(sub.fn) FROM "
            "(SELECT family_name AS fn FROM sqlonfhir.patient_demographics) sub"
        )
        assert result.valid is False

    def test_rejects_join_derived_table(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT sub.x_code, COUNT(*) FROM sqlonfhir.patient_demographics p "
            "JOIN (SELECT family_name AS x_code, patient_id FROM sqlonfhir.patient_demographics) sub "
            "ON sub.patient_id = p.patient_id GROUP BY sub.x_code"
        )
        assert result.valid is False

    def test_rejects_cte_relabeling_phi(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "WITH sub AS (SELECT family_name AS fn FROM sqlonfhir.patient_demographics) "
            "SELECT MIN(sub.fn) FROM sub"
        )
        assert result.valid is False
        assert any("cte" in v.lower() for v in result.violations)

    def test_accepts_where_clause_filter_subquery(self):
        # Filter-only subquery passes patient_ids around internally; nothing
        # PHI-shaped flows to output. Must stay allowed.
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT COUNT(*) FROM sqlonfhir.patient_demographics WHERE patient_id IN "
            "(SELECT patient_id FROM sqlonfhir.condition_simple WHERE code_text ILIKE '%diabetes%')"
        )
        assert result.valid is True, result.violations


class TestScalarSubqueryLaundering:
    """#95 re-review F9 — a scalar subquery in the SELECT list, paired with an
    aggregate so the old _contains_aggregate short-circuit skipped the whole
    item, surfaced raw PHI to output. Closed two ways: projection subqueries
    are banned, and aggregate output items must be pure aggregates."""

    def test_rejects_coalesce_scalar_subquery_with_count(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT COALESCE((SELECT family_name FROM sqlonfhir.patient_demographics LIMIT 1), "
            "CAST(COUNT(*) AS text)) FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False

    def test_rejects_case_guarded_scalar_subquery(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT CASE WHEN COUNT(*) >= 0 THEN "
            "(SELECT family_name FROM sqlonfhir.patient_demographics LIMIT 1) END "
            "FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False

    def test_rejects_correlated_per_group_scalar_subquery(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT gender, CASE WHEN COUNT(*) >= 0 THEN "
            "(SELECT p2.family_name FROM sqlonfhir.patient_demographics p2 "
            "WHERE p2.gender = pd.gender LIMIT 1) END "
            "FROM sqlonfhir.patient_demographics pd GROUP BY gender"
        )
        assert result.valid is False

    def test_rejects_bare_column_mixed_with_aggregate(self):
        # No subquery — a bare identifying column riding inside an aggregate
        # output item (the F9 root cause: short-circuit on "contains aggregate").
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT COALESCE(family_name, CAST(COUNT(*) AS text)) "
            "FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False
        assert any("mixes" in v.lower() for v in result.violations)

    def test_rejects_values_list_source(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT COUNT(*) FROM (VALUES (1),(2)) AS t(x)"
        )
        assert result.valid is False


class TestWindowFunctions:
    """#95 review F2 — windowed aggregates return per-row PHI."""

    def test_rejects_max_name_over_partition(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT MAX(family_name) OVER (PARTITION BY patient_id) "
            "FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False
        assert any("window" in v.lower() for v in result.violations)

    def test_rejects_count_over_empty_window(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT COUNT(*) OVER () FROM sqlonfhir.patient_demographics"
        )
        assert result.valid is False


class TestRowCap:
    """#95 review F4 — an attacker-supplied large LIMIT must be clamped."""

    def test_large_existing_limit_is_clamped(self):
        result = SQLValidator().validate(
            "SELECT gender, COUNT(*) FROM sqlonfhir.patient_demographics "
            "GROUP BY gender LIMIT 99999999"
        )
        assert result.valid is True
        assert "LIMIT 99999999" not in result.safe_sql
        assert "LIMIT 1000" in result.safe_sql

    def test_small_existing_limit_preserved(self):
        result = SQLValidator().validate(
            "SELECT gender, COUNT(*) FROM sqlonfhir.patient_demographics "
            "GROUP BY gender LIMIT 50"
        )
        assert result.valid is True
        assert "LIMIT 50" in result.safe_sql


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
    def test_cte_rejected_outright(self):
        # #95 re-review F8 hardened the #91 behavior: CTEs are now rejected
        # outright (a CTE can relabel a restricted column and launder it past
        # the output rules), rather than tolerated-with-inner-table-checks.
        result = SQLValidator().validate(
            "WITH x AS (SELECT patient_id FROM public.hfj_resource) SELECT COUNT(*) FROM x"
        )

        assert result.valid is False
        assert any("cte" in v.lower() for v in result.violations)


class TestAggregateOnlyOutput:
    """Rule 5 (#95) — the PHI boundary: every top-level output column is an
    aggregate or a grouped, non-identifying dimension. This rule is what makes
    ADR 0028's 'structurally cannot admit row-level PHI' claim true."""

    def test_rejects_bare_identifying_columns(self):
        result = SQLValidator().validate(
            "SELECT family_name, phone FROM sqlonfhir.patient_demographics"
        )

        assert result.valid is False
        assert any("aggregate" in v.lower() for v in result.violations)

    def test_rejects_select_star(self):
        result = SQLValidator().validate("SELECT * FROM sqlonfhir.patient_demographics")

        assert result.valid is False

    def test_rejects_distinct_patient_id_row_output(self):
        result = SQLValidator().validate(
            "SELECT DISTINCT patient_id FROM sqlonfhir.condition_simple"
        )

        assert result.valid is False

    def test_accepts_count_distinct(self):
        result = SQLValidator().validate(
            "SELECT COUNT(DISTINCT patient_id) FROM sqlonfhir.condition_simple"
        )

        assert result.valid is True

    def test_accepts_grouped_allowlisted_dimension(self):
        result = SQLValidator().validate(
            "SELECT gender, COUNT(DISTINCT patient_id) AS count "
            "FROM sqlonfhir.patient_demographics GROUP BY gender"
        )

        assert result.valid is True

    def test_accepts_age_bucket_case_expression_dimension(self):
        result = SQLValidator().validate(
            "SELECT CASE WHEN EXTRACT(YEAR FROM AGE(birth_date::date)) < 18 "
            "THEN 'minor' ELSE 'adult' END AS age_group, COUNT(DISTINCT patient_id) "
            "FROM sqlonfhir.patient_demographics "
            "GROUP BY CASE WHEN EXTRACT(YEAR FROM AGE(birth_date::date)) < 18 "
            "THEN 'minor' ELSE 'adult' END"
        )

        assert result.valid is True

    def test_rejects_group_by_identifying_column(self):
        result = SQLValidator().validate(
            "SELECT family_name, COUNT(*) FROM sqlonfhir.patient_demographics "
            "GROUP BY family_name"
        )

        assert result.valid is False
        assert any("family_name" in v for v in result.violations)

    def test_rejects_bare_birth_date_dimension(self):
        # Raw birth_date grouping is a quasi-identifier; only bucketed
        # expressions over birth_date are permitted as dimensions.
        result = SQLValidator().validate(
            "SELECT birth_date, COUNT(*) FROM sqlonfhir.patient_demographics " "GROUP BY birth_date"
        )

        assert result.valid is False

    def test_rejects_identity_wrapped_birth_date_dimensions(self):
        # #95 re-review F10: full DOB is a HIPAA Safe Harbor identifier.
        # Identity-preserving wraps satisfy "not bare" but return the raw date;
        # only AGE()-reduced buckets are permitted.
        wraps = [
            "SELECT birth_date::date, COUNT(*) FROM sqlonfhir.patient_demographics GROUP BY 1",
            "SELECT CAST(birth_date AS text), COUNT(*) FROM sqlonfhir.patient_demographics GROUP BY 1",
            "SELECT COALESCE(birth_date, ''), COUNT(*) FROM sqlonfhir.patient_demographics GROUP BY 1",
            "SELECT birth_date || '', COUNT(*) FROM sqlonfhir.patient_demographics GROUP BY 1",
            "SELECT LOWER(birth_date), COUNT(*) FROM sqlonfhir.patient_demographics GROUP BY 1",
            "SELECT TRIM(birth_date) AS d, COUNT(*) FROM sqlonfhir.patient_demographics GROUP BY d",
        ]
        for sql in wraps:
            result = SQLValidator().validate(sql)
            assert result.valid is False, f"leaked raw DOB: {sql}"

    def test_accepts_age_bucket_over_birth_date(self):
        result = SQLValidator().validate(
            "SELECT CASE WHEN EXTRACT(YEAR FROM AGE(birth_date::date)) < 18 "
            "THEN 'minor' ELSE 'adult' END AS age_group, COUNT(*) "
            "FROM sqlonfhir.patient_demographics GROUP BY 1"
        )
        assert result.valid is True, result.violations

    def test_rejects_bare_age_invertible_to_exact_dob(self):
        # #95 F11: AGE(birth_date) = age(CURRENT_DATE, birth_date) is invertible
        # against the known query date → exact DOB. An AGE ancestor alone is
        # NOT sufficient; only EXTRACT(YEAR FROM AGE(...)) is coarse.
        for sql in [
            "SELECT AGE(birth_date::date), COUNT(*) FROM sqlonfhir.patient_demographics GROUP BY 1",
            "SELECT EXTRACT(MONTH FROM AGE(birth_date::date)), COUNT(*) "
            "FROM sqlonfhir.patient_demographics GROUP BY 1",
            "SELECT EXTRACT(DAY FROM AGE(birth_date::date)), COUNT(*) "
            "FROM sqlonfhir.patient_demographics GROUP BY 1",
            "SELECT EXTRACT(YEAR FROM AGE(birth_date::date)) y, "
            "EXTRACT(MONTH FROM AGE(birth_date::date)) m, "
            "EXTRACT(DAY FROM AGE(birth_date::date)) d, COUNT(*) "
            "FROM sqlonfhir.patient_demographics GROUP BY 1, 2, 3",
        ]:
            result = SQLValidator(schemas=CANNED_SCHEMAS).validate(sql)
            assert result.valid is False, f"invertible DOB leak: {sql}"

    def test_accepts_extract_year_of_age(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT EXTRACT(YEAR FROM AGE(birth_date::date)) AS age, COUNT(*) "
            "FROM sqlonfhir.patient_demographics GROUP BY 1"
        )
        assert result.valid is True, result.violations

    def test_rejects_two_arg_age_with_attacker_anchor(self):
        # #95 H1: 2-arg AGE(anchor, birth_date) lets the caller pick an
        # arbitrary anchor; only single-arg AGE(birth_date) is permitted.
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT EXTRACT(YEAR FROM AGE(DATE '2000-01-01', birth_date::date)), COUNT(*) "
            "FROM sqlonfhir.patient_demographics GROUP BY 1"
        )
        assert result.valid is False

    def test_rejects_geographic_code_columns_latent(self):
        # #95 F12: zip_code / area_code end in `_code` but are geographic
        # identifiers; the token deny must catch them even if introspected in.
        schemas = {
            "patient_demographics": ViewSchema(
                name="patient_demographics",
                description="",
                columns=(
                    ColumnInfo("patient_id", "text"),
                    ColumnInfo("zip_code", "text"),
                    ColumnInfo("area_code", "text"),
                ),
            )
        }
        for col in ("zip_code", "area_code"):
            result = SQLValidator(schemas=schemas).validate(
                f"SELECT {col}, COUNT(*) FROM sqlonfhir.patient_demographics GROUP BY {col}"
            )
            assert result.valid is False, f"leaked geographic identifier: {col}"

    def test_accepts_clinical_code_display_dimensions(self):
        # The token deny must NOT over-reject legitimate clinical code/display
        # dimensions.
        schemas = {
            "condition_simple": ViewSchema(
                name="condition_simple",
                description="",
                columns=(
                    ColumnInfo("patient_id", "text"),
                    ColumnInfo("snomed_display", "text"),
                    ColumnInfo("icd10_code", "text"),
                ),
            )
        }
        for col in ("snomed_display", "icd10_code"):
            result = SQLValidator(schemas=schemas).validate(
                f"SELECT {col}, COUNT(DISTINCT patient_id) FROM sqlonfhir.condition_simple GROUP BY {col}"
            )
            assert result.valid is True, f"{col}: {result.violations}"

    def test_accepts_comparison_form_age_bucket(self):
        # birth_date in a WHEN comparison predicate is safe — the output is a
        # label, the raw date never flows out.
        result = SQLValidator().validate(
            "SELECT CASE WHEN birth_date::date > CURRENT_DATE - INTERVAL '18 years' "
            "THEN 'minor' ELSE 'adult' END AS ag, COUNT(*) "
            "FROM sqlonfhir.patient_demographics GROUP BY ag"
        )
        assert result.valid is True, result.violations

    def test_rejects_birth_date_in_case_then_value_position(self):
        # birth_date in a WHEN predicate is safe, but the SAME query outputting
        # birth_date in the THEN branch leaks the raw DOB — must reject.
        result = SQLValidator().validate(
            "SELECT CASE WHEN birth_date IS NOT NULL THEN birth_date ELSE 'x' END AS d, "
            "COUNT(*) FROM sqlonfhir.patient_demographics GROUP BY d"
        )
        assert result.valid is False

    def test_rejects_postal_code_dimension_despite_code_suffix(self):
        # #95 F11 — postal_code ends in `_code` (which the clinical-code suffix
        # allowlist waves through) but a ZIP is a HIPAA Safe Harbor identifier.
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT postal_code, COUNT(*) FROM sqlonfhir.patient_demographics GROUP BY postal_code"
        )
        assert result.valid is False

    def test_rejects_ungrouped_dimension_column(self):
        result = SQLValidator().validate(
            "SELECT gender, COUNT(*) FROM sqlonfhir.patient_demographics"
        )

        assert result.valid is False

    def test_accepts_inner_subquery_with_row_columns(self):
        # The aggregate-only rule applies to the OUTPUT; subqueries may pass
        # patient_ids around internally.
        result = SQLValidator().validate(
            "SELECT COUNT(*) FROM sqlonfhir.patient_demographics WHERE patient_id IN "
            "(SELECT patient_id FROM sqlonfhir.condition_simple WHERE code_text ILIKE '%diabetes%')"
        )

        assert result.valid is True


class TestColumnExistence:
    """Rule 4 (#95) — every referenced column must exist in the introspected
    schema of the view it's read from. The founding case: #76 was a stale
    `p.dob` reference (real column: birth_date) surviving because nothing
    checked columns against the live database."""

    def test_rejects_hallucinated_dob_column_the_76_case(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT COUNT(*) FROM sqlonfhir.patient_demographics p "
            "WHERE p.dob::date > CURRENT_DATE - INTERVAL '65 years'"
        )

        assert result.valid is False
        assert any("dob" in v for v in result.violations)

    def test_rejects_column_from_wrong_view(self):
        # patient_simple genuinely has no patient_id (live-verified in #91).
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT COUNT(*) FROM sqlonfhir.patient_simple p WHERE p.patient_id = 'x'"
        )

        assert result.valid is False
        assert any("patient_id" in v for v in result.violations)

    def test_accepts_valid_columns_across_joined_views(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p "
            "JOIN sqlonfhir.condition_simple c ON c.patient_id = p.patient_id "
            "WHERE p.gender = 'female' AND c.code_text ILIKE '%hypertension%'"
        )

        assert result.valid is True, result.violations

    def test_unqualified_column_checked_against_referenced_views(self):
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT COUNT(*) FROM sqlonfhir.patient_demographics WHERE nonexistent_col = 'x'"
        )

        assert result.valid is False
        assert any("nonexistent_col" in v for v in result.violations)

    def test_select_alias_reference_in_group_by_not_flagged(self):
        # `age_group` is a select alias, not a real column; GROUP BY may
        # legally reference it and the column rule must not false-positive.
        result = SQLValidator(schemas=CANNED_SCHEMAS).validate(
            "SELECT CASE WHEN birth_date::date > CURRENT_DATE - INTERVAL '18 years' "
            "THEN 'minor' ELSE 'adult' END AS age_group, COUNT(*) "
            "FROM sqlonfhir.patient_demographics GROUP BY age_group"
        )

        assert result.valid is True, result.violations

    def test_without_schemas_column_rule_is_skipped_not_guessed(self):
        # Bare SQLValidator() (tracer interface) has no column knowledge;
        # the synthesis path is REQUIRED to pass schemas (wiring test proves
        # it). Skipping beats guessing from a stale hardcoded list.
        result = SQLValidator().validate(
            "SELECT COUNT(*) FROM sqlonfhir.patient_demographics WHERE dob = 'x'"
        )

        assert result.valid is True


class TestFunctionAllowlist:
    """Rule 6 (#95) — deny-unknown function posture. pg_sleep DoS and
    pg_read_file exfil pass the tracer validator (no FROM clause -> table
    allowlist never fires); this rule is the fix (#91 review, PR #102)."""

    def test_rejects_pg_sleep(self):
        result = SQLValidator().validate("SELECT pg_sleep(999999)")

        assert result.valid is False
        assert any("pg_sleep" in v for v in result.violations)

    def test_rejects_pg_read_file(self):
        result = SQLValidator().validate("SELECT pg_read_file('/etc/passwd')")

        assert result.valid is False
        assert any("pg_read_file" in v for v in result.violations)

    def test_rejects_unknown_function_even_inside_aggregate(self):
        result = SQLValidator().validate(
            "SELECT COUNT(dblink('host=evil', 'SELECT 1')) FROM sqlonfhir.patient_simple"
        )

        assert result.valid is False
        assert any("dblink" in v for v in result.violations)

    def test_accepts_grilled_function_set(self):
        result = SQLValidator().validate(
            "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p "
            "JOIN sqlonfhir.observation_labs o ON o.patient_id = p.patient_id "
            "WHERE p.birth_date::date > CURRENT_DATE - INTERVAL '65 years' "
            "AND COALESCE(o.value_unit, '') = 'mg/dL' "
            "AND LOWER(o.code_display) LIKE '%glucose%' "
            "AND EXTRACT(YEAR FROM AGE(p.birth_date::date)) > 18"
        )

        assert result.valid is True, result.violations


class TestNormalization:
    """Rule 7 (#95) — valid SQL is re-rendered from the AST (comments cannot
    survive) with LIMIT injected when absent. Callers execute safe_sql, never
    the raw LLM output."""

    def test_safe_sql_strips_comments_and_injects_limit(self):
        result = SQLValidator().validate(
            "SELECT COUNT(*) FROM sqlonfhir.patient_demographics -- sneaky trailing comment"
        )

        assert result.valid is True
        assert result.safe_sql is not None
        assert "sneaky" not in result.safe_sql
        assert "LIMIT 1000" in result.safe_sql

    def test_existing_limit_is_preserved_not_doubled(self):
        result = SQLValidator().validate(
            "SELECT gender, COUNT(*) FROM sqlonfhir.patient_demographics GROUP BY gender LIMIT 50"
        )

        assert result.valid is True
        assert "LIMIT 50" in result.safe_sql
        assert "LIMIT 1000" not in result.safe_sql

    def test_invalid_sql_has_no_safe_sql(self):
        result = SQLValidator().validate("SELECT * FROM sqlonfhir.patient_demographics")

        assert result.valid is False
        assert result.safe_sql is None


class TestExplainDryRun:
    """Rule 8 (#95) — EXPLAIN against the live DB catches what static rules
    can't (type errors the planner sees). Static failures never reach the DB."""

    async def test_explain_success_keeps_result_valid(self):
        from unittest.mock import AsyncMock, MagicMock

        db = MagicMock()
        db.execute_query = AsyncMock(return_value=[{"QUERY PLAN": "Aggregate"}])

        result = await SQLValidator().validate_with_explain(
            "SELECT COUNT(*) FROM sqlonfhir.patient_demographics", db
        )

        assert result.valid is True
        explain_sql = db.execute_query.await_args.args[0]
        assert explain_sql.startswith("EXPLAIN ")

    async def test_explain_failure_invalidates_with_reason(self):
        from unittest.mock import AsyncMock, MagicMock

        db = MagicMock()
        db.execute_query = AsyncMock(side_effect=Exception("operator does not exist: text > date"))

        result = await SQLValidator().validate_with_explain(
            "SELECT COUNT(*) FROM sqlonfhir.patient_demographics", db
        )

        assert result.valid is False
        assert any("EXPLAIN" in v and "operator does not exist" in v for v in result.violations)

    async def test_static_failure_never_reaches_the_database(self):
        from unittest.mock import AsyncMock, MagicMock

        db = MagicMock()
        db.execute_query = AsyncMock()

        result = await SQLValidator().validate_with_explain(
            "SELECT family_name FROM sqlonfhir.patient_demographics", db
        )

        assert result.valid is False
        db.execute_query.assert_not_called()


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
