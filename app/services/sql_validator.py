"""SQL Validator — deterministic default-deny gate for LLM-synthesized
exploratory SQL.

Sprint 6.7: #91 tracer rules + #95 full rule set (ADR 0028 decision 4):

 1. sqlglot parse, postgres dialect
 2. exactly one statement, SELECT-only (SELECT INTO rejected as a write)
 3. table refs restricted to the 7 sqlonfhir views; catalog qualifiers rejected
 4. column existence against the live introspected schema (#94 pg_catalog)
 5. aggregate-only output + non-identifying dimension allowlist (PHI boundary)
 6. function allowlist — deny unknown (pg_sleep, pg_read_file, dblink, ...)
 7. normalization: comments stripped, LIMIT injected (safe_sql)
 8. EXPLAIN dry-run (async, validate_with_explain)

Structural failures (parse / statement count / statement type) return early;
all other rules accumulate, because #96's retry loop appends the violation
text to the resynthesis prompt and needs the complete picture. Violation
messages name the rule broken — they are part of the contract.
"""

import logging
from dataclasses import dataclass, field
from typing import List

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

logger = logging.getLogger(__name__)

SCHEMA_NAME = "sqlonfhir"

# The 7 production views — the NAME authority (which relations are queryable
# at all). #94 made pg_catalog introspection the COLUMN authority for the
# synthesis prompt, consuming this set as its expected-views list; #95 wires
# the same introspection into column-existence checks here. (pg_catalog, not
# information_schema — the 4 custom-path MVs don't appear in the latter.)
ALLOWED_VIEWS = frozenset(
    {
        "patient_simple",
        "patient_demographics",
        "condition_simple",
        "condition_diagnoses",
        "observation_labs",
        "medication_requests",
        "procedure_history",
    }
)

# Rule 5 — non-identifying output dimensions (ADR 0028 decision 2): gender,
# clinical_status, coded/display columns. birth_date may appear ONLY inside a
# bucketing expression (CASE/EXTRACT/AGE), never as a bare output dimension.
_DIMENSION_ALLOWED_EXACT = frozenset({"gender", "clinical_status"})
_DIMENSION_ALLOWED_SUFFIXES = ("_display", "_code")
# Identifying columns that a suffix match would otherwise wave through —
# `postal_code` ends in `_code` but a ZIP is a HIPAA Safe Harbor identifier.
# These are NEVER dimensions regardless of suffix.
_DIMENSION_DENY_EXACT = frozenset({"postal_code", "patient_id", "id", "phone", "email"})
# Geographic / contact / name identifier tokens — any column whose name
# CONTAINS one is denied even if it ends in an allowed suffix (e.g. a future
# `zip_code`, `area_code`, `county_code`). The suffix allowlist is open-ended
# and columns come from live introspection, so this fails safe toward deny
# rather than naming every bad column (#95 F12).
_DIMENSION_DENY_TOKENS = (
    "zip",
    "postal",
    "area_code",
    "county",
    "region",
    "district",
    "census",
    "tract",
    "phone",
    "fax",
    "email",
    "address",
    "_name",
    "ssn",
    "mrn",
)
_BUCKETABLE_COLUMNS = frozenset({"birth_date"})

# Rule 6 — grilled function allowlist. Aggregates are enumerated EXPLICITLY,
# NOT via exp.AggFunc: that superclass also covers the concatenating
# aggregates (string_agg->GroupConcat, array_agg->ArrayAgg,
# json_agg->JSONArrayAgg) which exfiltrate raw column values into a single
# "aggregate" cell. Only cardinality/numeric-reducing aggregates are safe.
_ALLOWED_AGG_CLASSES = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
# Min/Max/Sum/Avg surface or compute a VALUE from their argument; their
# argument columns must be numeric (checked against introspected types) so
# they can't leak a real name/DOB. Count returns only a cardinality — exempt.
_VALUE_AGG_CLASSES = (exp.Sum, exp.Avg, exp.Min, exp.Max)
# exp.Connector covers AND/OR (they are Func subclasses in sqlglot).
_ALLOWED_FUNC_CLASSES = tuple(
    c
    for c in (
        *_ALLOWED_AGG_CLASSES,
        exp.Cast,
        exp.Case,
        exp.If,
        exp.Extract,
        exp.Coalesce,
        exp.Lower,
        exp.Upper,
        exp.Trim,
        exp.CurrentDate,
        exp.CurrentTimestamp,
        exp.Connector,
        exp.Not,
        getattr(exp, "DateTrunc", None),
        getattr(exp, "TimestampTrunc", None),
    )
    if c is not None
)
_ALLOWED_ANONYMOUS_FUNCS = frozenset({"age", "date_part", "date_trunc"})

# Comparison/predicate nodes — a birth_date occurrence under one of these is in
# a boolean predicate (the `WHEN birth_date::date > cutoff` age-bucket form),
# not flowing its raw value to output.
_COMPARISON_CLASSES = tuple(
    c
    for c in (
        exp.GT,
        exp.GTE,
        exp.LT,
        exp.LTE,
        exp.EQ,
        exp.NEQ,
        exp.Is,
        exp.In,
        exp.Between,
        exp.Like,
        exp.ILike,
    )
    if c is not None
)

# Postgres numeric type names (format_type output) legal as value-aggregate
# arguments. Dates are stored as TEXT in these MVs, so MIN/MAX over birth_date
# is rejected here too — that closes the exact-DOB leak, not just names.
_NUMERIC_TYPE_TOKENS = (
    "integer",
    "bigint",
    "smallint",
    "numeric",
    "decimal",
    "real",
    "double precision",
)


_INJECTED_LIMIT = 1000


@dataclass
class ValidationResult:
    valid: bool
    violations: List[str] = field(default_factory=list)
    # Rule 7: re-rendered from the AST (comments cannot survive) with LIMIT
    # injected when absent. Callers execute THIS, never the raw LLM output.
    # None whenever valid is False.
    safe_sql: "str | None" = None
    # The sqlonfhir views this query reads — feeds get_batch_anchor_ts_for_views
    # for the "data as of <ts>" disclosure (#97). Empty when invalid.
    touched_views: List[str] = field(default_factory=list)


class SQLValidationError(Exception):
    """Synthesized SQL failed validation. #96 replaces raise-to-caller with the
    honest-error variant; until then callers must not swallow this into a 0."""

    def __init__(self, violations: List[str]):
        self.violations = violations
        super().__init__("; ".join(violations))


def _contains_aggregate(node: exp.Expression) -> bool:
    # Only ALLOWED aggregates count — a concatenating aggregate does NOT make
    # an output column safe (rule 6 rejects it too; this is defense in depth).
    return any(isinstance(f, _ALLOWED_AGG_CLASSES) for f in node.find_all(exp.Func))


def _dimension_column_allowed(name: str) -> bool:
    if name in _DIMENSION_DENY_EXACT or any(tok in name for tok in _DIMENSION_DENY_TOKENS):
        return False
    return name in _DIMENSION_ALLOWED_EXACT or name.endswith(_DIMENSION_ALLOWED_SUFFIXES)


class SQLValidator:
    """Default-deny validation of synthesized SQL before execution.

    ``schemas`` is the live-introspected view map from
    schema_introspection.get_cached_schemas() (duck-typed here to avoid a
    circular import — that module imports ALLOWED_VIEWS from this one). The
    synthesis path MUST pass it (wiring-test-enforced); without it the
    column-existence rule is skipped, never guessed from a stale list.
    """

    def __init__(self, schemas=None):
        self.schemas = schemas

    def validate(self, sql: str) -> ValidationResult:
        try:
            statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
        except ParseError as e:
            return ValidationResult(valid=False, violations=[f"SQL failed to parse: {e}"])

        if len(statements) != 1:
            return ValidationResult(
                valid=False,
                violations=[f"exactly one SQL statement is required, got {len(statements)}"],
            )

        stmt = statements[0]
        if not isinstance(stmt, exp.Select):
            return ValidationResult(
                valid=False,
                violations=[f"only SELECT statements are permitted, got {stmt.key.upper()}"],
            )

        # Postgres SELECT INTO parses as exp.Select but is CREATE TABLE AS — a write.
        if stmt.args.get("into"):
            return ValidationResult(
                valid=False,
                violations=["SELECT INTO is a write and is not permitted; use plain SELECT"],
            )

        violations: List[str] = []
        # Window functions return per-row output (MAX(name) OVER (...) yields
        # one row per patient) — no legitimate use in aggregate-only counting.
        if any(True for _ in stmt.find_all(exp.Window)):
            violations.append(
                "window functions (OVER (...)) return per-row output and are "
                "not permitted; use plain aggregates"
            )
        # Derived tables (FROM-clause subqueries) and CTEs can relabel a PHI
        # column (family_name AS gender) so it launders past the dimension
        # allowlist and the numeric-type check (#95 re-review F8). The
        # synthesis prompt bans CTEs and never emits FROM-subqueries, so both
        # are rejected outright. WHERE-clause filter subqueries are unaffected
        # (nothing PHI-shaped flows from them to output).
        self._check_no_derived_sources(stmt, violations)
        source_map = self._build_source_map(stmt)
        self._check_tables(stmt, violations)
        if self.schemas:
            self._check_columns(stmt, source_map, violations)
            self._check_value_aggregate_types(stmt, source_map, violations)
        self._check_aggregate_only_output(stmt, violations)
        self._check_functions(stmt, violations)

        if violations:
            logger.info("SQL validation rejected query: %s", violations)
            return ValidationResult(valid=False, violations=violations)

        touched_views = sorted(
            {
                t.name
                for t in stmt.find_all(exp.Table)
                if t.db == SCHEMA_NAME and t.name in ALLOWED_VIEWS
            }
        )

        # Rule 7: normalize — comments dropped in the re-render; cap rows at
        # <= _INJECTED_LIMIT (an attacker-supplied larger LIMIT is clamped, not
        # preserved — it's the only bound on breakdown row counts).
        stmt = self._apply_row_cap(stmt)
        return ValidationResult(
            valid=True,
            violations=[],
            safe_sql=stmt.sql(dialect="postgres", comments=False),
            touched_views=touched_views,
        )

    @staticmethod
    def _apply_row_cap(stmt: exp.Select) -> exp.Select:
        limit = stmt.args.get("limit")
        if limit is None:
            return stmt.limit(_INJECTED_LIMIT)
        expr = limit.expression
        try:
            current = int(expr.name)
        except (AttributeError, ValueError):
            # Non-literal LIMIT (expression/param) — replace with a safe literal.
            return stmt.limit(_INJECTED_LIMIT)
        if current > _INJECTED_LIMIT:
            return stmt.limit(_INJECTED_LIMIT)
        return stmt

    async def validate_with_explain(self, sql: str, db_client) -> ValidationResult:
        """All 8 rules: static rules 1-7, then rule 8 — EXPLAIN dry-run against
        the live database. Static failures never reach the DB."""
        result = self.validate(sql)
        if not result.valid:
            return result
        try:
            await db_client.execute_query(f"EXPLAIN {result.safe_sql}")
        except Exception as e:
            return ValidationResult(
                valid=False,
                violations=[f"EXPLAIN dry-run failed against the live database: {e}"],
            )
        return result

    # -- rule 3: table allowlist ------------------------------------------

    def _check_tables(self, stmt: exp.Select, violations: List[str]) -> None:
        # CTE aliases are query-local names, not tables; their INNER table refs
        # are still scanned below, so laundering through a CTE is still caught.
        cte_aliases = {cte.alias for cte in stmt.find_all(exp.CTE)}

        for table in stmt.find_all(exp.Table):
            if not table.db and table.name in cte_aliases:
                continue
            qualified = ".".join(p for p in (table.catalog, table.db, table.name) if p)
            if table.catalog:
                violations.append(
                    f"table '{qualified}' uses a catalog qualifier ('{table.catalog}'); "
                    f"only {SCHEMA_NAME}-schema references are permitted"
                )
            elif table.db != SCHEMA_NAME or table.name not in ALLOWED_VIEWS:
                violations.append(
                    f"table '{qualified}' is not an allowed view; permitted tables are "
                    f"{SCHEMA_NAME}.{{{', '.join(sorted(ALLOWED_VIEWS))}}}"
                )

    # -- rule 3b: no derived / relabeling sources --------------------------

    @staticmethod
    def _subquery_is_filter_only(subquery: exp.Subquery) -> bool:
        """True only if this Subquery sits inside a WHERE/HAVING filter. A
        subquery in FROM (derived table) or in the SELECT list (scalar
        subquery) can relabel a restricted column and launder it to output —
        walk the parent chain: first From/Join/Select ancestor => output-
        flowing (reject); first Where/Having ancestor => filter-only (allow)."""
        p = subquery.parent
        while p is not None:
            if isinstance(p, (exp.Where, exp.Having)):
                return True
            if isinstance(p, (exp.From, exp.Join, exp.Lateral, exp.Select)):
                return False
            p = p.parent
        return False

    def _check_no_derived_sources(self, stmt: exp.Select, violations: List[str]) -> None:
        if any(True for _ in stmt.find_all(exp.CTE)):
            violations.append(
                "CTEs (WITH ...) are not permitted; a CTE can relabel a "
                "restricted column and launder it past the output rules"
            )
        if any(not self._subquery_is_filter_only(sq) for sq in stmt.find_all(exp.Subquery)):
            violations.append(
                "subqueries are permitted only in WHERE/HAVING filters; a "
                "subquery in FROM or the SELECT list can relabel a restricted "
                "column and launder it past the output rules"
            )
        if any(True for _ in stmt.find_all(exp.Values)):
            violations.append("VALUES lists are not permitted as a data source")

    # -- rule 4: column existence against introspected schema --------------

    def _build_source_map(self, stmt: exp.Select) -> dict:
        """alias/name -> view name, for allowed sqlonfhir tables in this query."""
        source_map = {}
        if not self.schemas:
            return source_map
        for table in stmt.find_all(exp.Table):
            if table.db == SCHEMA_NAME and table.name in self.schemas:
                source_map[table.alias_or_name] = table.name
        return source_map

    def _column_pg_type(self, col: exp.Column, source_map: dict):
        """Resolve a column's introspected pg_type, or None if unresolvable."""
        views = [source_map[col.table]] if col.table in source_map else list(source_map.values())
        for view in views:
            for c in self.schemas[view].columns:
                if c.name == col.name:
                    return c.pg_type
        return None

    def _check_columns(self, stmt: exp.Select, source_map: dict, violations: List[str]) -> None:
        cte_aliases = {cte.alias for cte in stmt.find_all(exp.CTE)}
        select_aliases = {sel.alias for sel in stmt.expressions if isinstance(sel, exp.Alias)}
        referenced_views = set(source_map.values())
        union_cols = {col.name for view in referenced_views for col in self.schemas[view].columns}

        for col in stmt.find_all(exp.Column):
            cname = col.name
            tref = col.table
            if tref:
                if tref in cte_aliases:
                    continue
                view = source_map.get(tref)
                if view is None:
                    continue  # unknown source; the table rule already flagged it
                view_cols = {c.name for c in self.schemas[view].columns}
                if cname not in view_cols:
                    violations.append(
                        f"column '{tref}.{cname}' does not exist in "
                        f"{SCHEMA_NAME}.{view}; its columns are: "
                        f"{', '.join(sorted(view_cols))}"
                    )
            else:
                if cname in select_aliases:
                    continue
                if referenced_views and cname not in union_cols:
                    violations.append(
                        f"column '{cname}' does not exist in any referenced view "
                        f"({', '.join(sorted(referenced_views))})"
                    )

    def _check_value_aggregate_types(
        self, stmt: exp.Select, source_map: dict, violations: List[str]
    ) -> None:
        """MIN/MAX/SUM/AVG argument columns must be numeric — a text-column
        value aggregate leaks a real name or DOB (F3). Requires schemas."""
        for agg in stmt.find_all(_VALUE_AGG_CLASSES):
            for col in agg.find_all(exp.Column):
                pg_type = self._column_pg_type(col, source_map)
                if pg_type is None:
                    continue  # unresolved column is rule 4's job to flag
                if not any(tok in pg_type for tok in _NUMERIC_TYPE_TOKENS):
                    ref = f"{col.table}.{col.name}" if col.table else col.name
                    msg = (
                        f"{type(agg).__name__.upper()} over non-numeric column "
                        f"'{ref}' ({pg_type}) is not permitted — it would expose a "
                        f"raw value; value aggregates are allowed only over numeric columns"
                    )
                    if msg not in violations:
                        violations.append(msg)

    # -- rule 5: aggregate-only output + dimension allowlist ---------------

    def _check_aggregate_only_output(self, stmt: exp.Select, violations: List[str]) -> None:
        group = stmt.args.get("group")
        group_sqls = {g.sql(dialect="postgres") for g in group.expressions} if group else set()
        alias_to_expr = {
            sel.alias: sel.this for sel in stmt.expressions if isinstance(sel, exp.Alias)
        }

        for idx, sel in enumerate(stmt.expressions, start=1):
            inner = sel.this if isinstance(sel, exp.Alias) else sel
            if isinstance(inner, exp.Star):
                violations.append(
                    "SELECT * outputs raw rows; only aggregate outputs "
                    "(COUNT/AVG/SUM/MIN/MAX, optionally grouped) are permitted"
                )
                continue
            if _contains_aggregate(inner):
                # An aggregate output item must be a PURE aggregate: every
                # column reduced inside an allowed aggregate. A free column
                # riding alongside the aggregate (COALESCE(family_name,
                # COUNT(*))) surfaces raw PHI (#95 re-review F9).
                free = self._free_columns(inner)
                if free:
                    names = ", ".join(sorted({c.name for c in free}))
                    violations.append(
                        f"output expression '{sel.sql(dialect='postgres')}' mixes an "
                        f"aggregate with non-aggregate column(s) ({names}); an "
                        f"aggregate output must reduce every column it references"
                    )
                continue
            grouped = (
                inner.sql(dialect="postgres") in group_sqls
                or str(idx) in group_sqls
                or (isinstance(sel, exp.Alias) and sel.alias in group_sqls)
            )
            if not grouped:
                violations.append(
                    f"output column '{sel.sql(dialect='postgres')}' is neither an "
                    f"aggregate nor a GROUP BY dimension; only aggregate outputs are permitted"
                )
                continue
            self._check_dimension_expression(inner, violations)

        if group:
            for g in group.expressions:
                if isinstance(g, exp.Literal):
                    continue  # positional GROUP BY 1 — covered via the select side
                if isinstance(g, exp.Column) and not g.table and g.name in alias_to_expr:
                    # GROUP BY <select alias>: check the aliased expression,
                    # not the alias name (which is not a real column).
                    self._check_dimension_expression(alias_to_expr[g.name], violations)
                    continue
                self._check_dimension_expression(g, violations)

    @staticmethod
    def _free_columns(expr: exp.Expression) -> List[exp.Column]:
        """Columns in expr NOT reduced inside an allowed aggregate — i.e. those
        that would surface a raw value to output."""
        free = []
        for col in expr.find_all(exp.Column):
            p = col
            enclosed = False
            while p is not None:
                if isinstance(p, _ALLOWED_AGG_CLASSES):
                    enclosed = True
                    break
                if p is expr:
                    break
                p = p.parent
            if not enclosed:
                free.append(col)
        return free

    @staticmethod
    def _birth_date_occurrence_safe(col: exp.Column, root: exp.Expression) -> bool:
        """A birth_date occurrence is safe iff its raw value cannot flow to
        output in any date-finer-than-year form:
          (a) inside a comparison/predicate — yields a boolean, e.g. the
              `WHEN birth_date::date > cutoff` age-bucket form; or
          (b) inside `EXTRACT(YEAR FROM AGE(birth_date...))` — whole-year age.

        Bare `AGE(birth_date)` is INVERTIBLE (age(CURRENT_DATE, birth_date) vs a
        known query date -> exact DOB), and `EXTRACT(MONTH|DAY FROM AGE(...))`
        leaks the birth month/day, so an AGE ancestor alone is NOT sufficient
        (#95 F11). Identity-preserving wraps never qualify (#95 F10)."""
        p = col.parent
        age_node = None
        while p is not None:
            if isinstance(p, _COMPARISON_CLASSES):
                return True
            if isinstance(p, exp.Anonymous) and p.name.lower() == "age":
                age_node = p
                break
            if p is root:
                return False
            p = p.parent
        if age_node is None:
            return False
        # Two-arg AGE(anchor, birth_date) lets the caller pick an arbitrary
        # anchor instead of "now" — no legit use here (the age bucket is
        # single-arg AGE(birth_date)) and it sharpens the small-cell oracle
        # (#95 H1). Only single-arg AGE is permitted.
        if len(age_node.expressions) != 1:
            return False
        # Under AGE — safe ONLY if coarsened to whole years by EXTRACT(YEAR),
        # or the AGE interval is itself compared (bool out).
        q = age_node.parent
        while q is not None:
            if isinstance(q, _COMPARISON_CLASSES):
                return True
            if isinstance(q, exp.Extract):
                field = (q.this.name or "").upper() if q.this else ""
                return field == "YEAR"
            if q is root:
                break
            q = q.parent
        return False

    def _check_dimension_expression(self, node: exp.Expression, violations: List[str]) -> None:
        bare = isinstance(node, exp.Column)
        columns = [node] if bare else list(node.find_all(exp.Column))
        for col in columns:
            name = col.name
            if _dimension_column_allowed(name):
                continue
            # birth_date is a quasi-identifier (full DOB = HIPAA Safe Harbor
            # identifier). It may reach a dimension ONLY reduced through AGE()
            # — "wrapped in any function" (the old `not bare` test) let
            # CAST/COALESCE/||/LOWER launder the raw date to output (#95 F10).
            if name in _BUCKETABLE_COLUMNS and self._birth_date_occurrence_safe(col, node):
                continue
            msg = (
                f"column '{name}' is not permitted as an output dimension; allowed "
                f"dimensions are gender, clinical_status, *_display, *_code columns, "
                f"or age buckets via AGE(birth_date)"
            )
            if msg not in violations:
                violations.append(msg)

    # -- rule 6: function allowlist ----------------------------------------

    def _check_functions(self, stmt: exp.Select, violations: List[str]) -> None:
        for func in stmt.find_all(exp.Func):
            if isinstance(func, exp.Anonymous):
                fname = func.name
                if fname.lower() not in _ALLOWED_ANONYMOUS_FUNCS:
                    msg = (
                        f"function '{fname}' is not permitted; allowed functions are "
                        f"COUNT/AVG/SUM/MIN/MAX, EXTRACT, AGE, DATE_TRUNC, DATE_PART, "
                        f"COALESCE, CASE, CAST, LOWER/UPPER/TRIM, CURRENT_DATE"
                    )
                    if msg not in violations:
                        violations.append(msg)
            elif not isinstance(func, _ALLOWED_FUNC_CLASSES):
                fname = type(func).__name__
                msg = (
                    f"function '{fname}' is not permitted; allowed functions are "
                    f"COUNT/AVG/SUM/MIN/MAX, EXTRACT, AGE, DATE_TRUNC, DATE_PART, "
                    f"COALESCE, CASE, CAST, LOWER/UPPER/TRIM, CURRENT_DATE"
                )
                if msg not in violations:
                    violations.append(msg)
