"""
FHIRPath to SQL Transpiler

Converts FHIRPath expressions (from SQL-on-FHIR ViewDefinitions)
to PostgreSQL JSONB queries for execution against HAPI FHIR database.

Supported FHIRPath features:
- Simple field access: "gender", "birthDate"
- Nested fields: "name.family", "address.city"
- Array navigation: "name.given" (first element), "name.given.all()" (all elements)
- where() clause: "coding.where(system='http://loinc.org')"
- first(), exists(), count(), empty()
- Type casting: toInteger(), toString(), toDateTime()

Example conversions:
  FHIRPath: "name.family"
  SQL: v.res_text_vc::jsonb->'name'->0->>'family'

  FHIRPath: "code.coding.where(system='http://loinc.org').code"
  SQL: (SELECT coding->>'code' FROM jsonb_array_elements(...) WHERE ...)
"""

import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FHIRPathExpression:
    """Parsed FHIRPath expression"""

    path: str  # Original FHIRPath
    sql: str  # Transpiled SQL
    requires_subquery: bool = False  # True if needs lateral join
    array_alias: Optional[str] = None  # Alias for jsonb_array_elements


class FHIRPathTranspiler:
    """
    Transpiles FHIRPath expressions to PostgreSQL JSONB queries

    Handles the subset of FHIRPath used in SQL-on-FHIR ViewDefinitions
    """

    def __init__(self, resource_alias: str = "v", resource_column: str = "res_text_vc"):
        """
        Initialize transpiler

        Args:
            resource_alias: Table alias for resource version table (default: 'v')
            resource_column: Column name containing JSONB resource (default: 'res_text_vc')
        """
        self.resource_alias = resource_alias
        self.resource_column = resource_column
        self._array_counter = 0  # For generating unique array aliases

    def transpile(
        self, fhir_path: str, as_text: bool = True, context_path: Optional[str] = None
    ) -> FHIRPathExpression:
        """
        Transpile FHIRPath expression to SQL

        Args:
            fhir_path: FHIRPath expression
            as_text: If True, use ->> for text output; if False, use -> for jsonb
            context_path: Optional context path (for forEach expressions)

        Returns:
            FHIRPathExpression with transpiled SQL
        """
        # Strip whitespace
        fhir_path = fhir_path.strip()

        # Handle empty path
        if not fhir_path or fhir_path == ".":
            base_path = f"{self.resource_alias}.{self.resource_column}::jsonb"
            if context_path:
                base_path = context_path
            return FHIRPathExpression(path=fhir_path, sql=base_path)

        # Check for string concatenation with + operator
        if " + " in fhir_path:
            return self._transpile_concatenation(fhir_path, as_text, context_path)

        # Check for where() clause
        if ".where(" in fhir_path:
            return self._transpile_where_clause(fhir_path, as_text, context_path)

        # Check for function calls
        if ".first()" in fhir_path:
            return self._transpile_first(fhir_path, as_text, context_path)

        if ".exists()" in fhir_path:
            return self._transpile_exists(fhir_path, context_path)

        if ".count()" in fhir_path:
            return self._transpile_count(fhir_path, context_path)

        if ".empty()" in fhir_path:
            return self._transpile_empty(fhir_path, context_path)

        # Simple field path (most common case)
        return self._transpile_simple_path(fhir_path, as_text, context_path)

    def transpile_where_predicate(self, expr: str) -> str:
        """Transpile a FHIRPath boolean expression for use in a SQL WHERE clause.

        Bug 11 fix (issue #11): the previous implementation routed where-clause paths
        through `transpile()` which treats them as field navigation, producing SQL like
        `jsonb->'active = true or active'->'not()' IS NOT NULL` (literal JSON-key access).
        WHERE-clause expressions are predicates, not paths.

        Supported patterns (the only ones used in current view defs that we're targeting):
        - Boolean OR: `<a> or <b>` recursively transpiled and joined with SQL OR
        - Boolean AND: `<a> and <b>` recursively transpiled and joined with SQL AND
        - Field equality: `field = value` -> `jsonb->>'field' = '<value>'`
        - Existence: `field.exists()` -> `jsonb->'field' IS NOT NULL`
        - Negated existence: `field.exists().not()` -> `jsonb->'field' IS NULL`

        Unsupported patterns (used by 4 of 7 view defs, blocked by issue #12+ scope):
        `field in (a | b | c)`, `path.where(condition).exists()` with multi-arg condition,
        `$this in (...)`. Logs a warning and returns SQL `true` so the where clause
        becomes a no-op rather than producing a syntax error.

        Returns: bare predicate SQL (no surrounding parens).
        """
        expr = expr.strip()
        if not expr:
            return "true"

        # Split on top-level boolean operators (lowest precedence first).
        # We only split on " or "/" and " surrounded by spaces so quoted strings or
        # field-name substrings don't trigger false splits. Top-level only — no paren
        # nesting in the patterns we support today.
        for op_kw, op_sql in ((" or ", " OR "), (" and ", " AND ")):
            parts = self._split_top_level_kw(expr, op_kw)
            if len(parts) > 1:
                return op_sql.join(f"({self.transpile_where_predicate(p)})" for p in parts)

        # Single term: dispatch by suffix
        if expr.endswith(".exists().not()"):
            path = expr[: -len(".exists().not()")]
            inner = self._transpile_simple_path(path, as_text=False, context_path=None).sql
            return f"{inner} IS NULL"

        if expr.endswith(".exists()"):
            path = expr[: -len(".exists()")]
            inner = self._transpile_simple_path(path, as_text=False, context_path=None).sql
            return f"{inner} IS NOT NULL"

        # field = value (handle both 'true'/'false' literals and quoted strings)
        if " = " in expr:
            left, right = expr.split(" = ", 1)
            left_sql = self._transpile_simple_path(
                left.strip(), as_text=True, context_path=None
            ).sql
            right = right.strip()
            if right in ("true", "false"):
                return f"{left_sql} = '{right}'"
            if right.startswith("'") and right.endswith("'"):
                return f"{left_sql} = {right}"
            # Bare identifier or number — quote it
            return f"{left_sql} = '{right}'"

        # field in (a | b | c) — issue #12 extension to Bug 11.
        # Used by procedure_history, medication_requests, observation_labs WHERE
        # clauses for status enums. FHIRPath uses `|` as the union operator inside
        # parens; we map to SQL IN list.
        in_match = re.match(r"^(\S+)\s+in\s+\((.+)\)$", expr)
        if in_match:
            field_path = in_match.group(1)
            values_blob = in_match.group(2)
            field_sql = self._transpile_simple_path(field_path, as_text=True, context_path=None).sql
            # Split values on |, strip quotes/whitespace
            values = [v.strip().strip("'\"") for v in values_blob.split("|")]
            value_list = ", ".join(f"'{v}'" for v in values)
            return f"{field_sql} IN ({value_list})"

        logger.warning("Unsupported where-clause pattern, emitting 'true' (no-op): %s", expr)
        return "true"

    @staticmethod
    def _split_top_level_kw(expr: str, sep: str) -> List[str]:
        """Split `expr` on `sep` at top level only (skipping inside parens).

        Used by transpile_where_predicate to split on top-level boolean operators
        without splitting inside nested function calls or quoted strings.
        """
        parts: List[str] = []
        depth = 0
        in_quote = False
        i = 0
        last = 0
        while i < len(expr):
            ch = expr[i]
            if ch == "'":
                in_quote = not in_quote
            elif not in_quote:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif depth == 0 and expr[i : i + len(sep)] == sep:
                    parts.append(expr[last:i])
                    last = i + len(sep)
                    i += len(sep)
                    continue
            i += 1
        parts.append(expr[last:])
        return [p.strip() for p in parts if p.strip()]

    def _transpile_simple_path(
        self, fhir_path: str, as_text: bool, context_path: Optional[str]
    ) -> FHIRPathExpression:
        """
        Transpile simple field path like "name.family" or "birthDate"

        Args:
            fhir_path: Simple field path
            as_text: Use ->> for final element
            context_path: Optional context for nested paths

        Returns:
            FHIRPathExpression with JSONB path
        """
        # Bug 2 fix (issue #11): top-level FHIR [x] choice field. Coalesce across
        # all known variants. Only fires when there's no context (top-level access);
        # nested choice fields are rare and not currently used by any view def.
        if not context_path and fhir_path in self._CHOICE_FIELDS:
            base = f"{self.resource_alias}.{self.resource_column}::jsonb"
            op = "->>" if as_text else "->"
            variants = ", ".join(f"{base}{op}'{v}'" for v in self._CHOICE_FIELDS[fhir_path])
            return FHIRPathExpression(path=fhir_path, sql=f"COALESCE({variants})")

        segments = fhir_path.split(".")

        # Bug 4/6 fix (issue #12): function-call segments like split('/'), last(),
        # replace('Patient/', '') need real function dispatch, not literal JSON-key
        # access. Find the first function call, transpile the prefix as text (since
        # text functions consume text), then chain the function calls.
        for i, seg in enumerate(segments):
            if self._FUNCTION_CALL_RE.match(seg):
                prefix_path = ".".join(segments[:i])
                if prefix_path:
                    prefix_sql = self._transpile_simple_path(
                        prefix_path, as_text=True, context_path=context_path
                    ).sql
                else:
                    prefix_sql = context_path or (
                        f"{self.resource_alias}.{self.resource_column}::jsonb"
                    )
                return self._apply_function_chain(prefix_sql, segments[i:], fhir_path)

        # Start with resource or context
        if context_path:
            base = context_path
        else:
            base = f"{self.resource_alias}.{self.resource_column}::jsonb"

        # Build JSONB navigation
        sql_parts = [base]

        # Bug 3 fix (issue #11): array-typed FHIR fields need ->'segment'->0 (navigate
        # to the array, then take element 0), not ->0->'segment' (which evaluates ->0
        # on the resource OBJECT, returning NULL). The previous order produced
        # syntactically valid but semantically NULL SQL for every plain `name.X` /
        # `address.X` path outside forEach. forEach contexts use _transpile_where_clause
        # which already handles arrays correctly, so this bug only fires for non-forEach
        # paths.
        for i, segment in enumerate(segments):
            is_last = i == len(segments) - 1
            is_array = segment in self._ARRAY_FIELDS

            # Field access first
            if is_last and as_text and not is_array:
                sql_parts.append(f"->>'{segment}'")
            else:
                sql_parts.append(f"->'{segment}'")

            # Then take first element if it's a known array field AND there's more
            # path to traverse (or we need text of the first element)
            if is_array:
                if is_last and as_text:
                    sql_parts.append("->>0")
                else:
                    sql_parts.append("->0")

        sql = "".join(sql_parts)

        return FHIRPathExpression(path=fhir_path, sql=sql)

    def _apply_function_chain(
        self, prefix_sql: str, fn_segments: List[str], orig_path: str
    ) -> FHIRPathExpression:
        """Apply chained string/array function calls starting from a text expression.

        Bug 4 + Bug 6 fix (issue #12). Each segment is matched as `funcname(args)`
        and dispatched to its SQL equivalent. The chain starts from a text
        expression (callers pass prefix_sql with as_text=True semantics) since
        Postgres functions like split/replace consume text.

        Supported:
        - split(sep) → regexp_split_to_array(text, sep) returning text[]
        - last() → arr[array_length(arr, 1)] (assumes preceding result is text[])
        - replace(from, to) → replace(text, from, to)

        Unsupported function names log a warning and emit literal JSON-key access
        (preserves the bug-style output so it stays visible).
        """
        current = prefix_sql
        for seg in fn_segments:
            m = self._FUNCTION_CALL_RE.match(seg)
            if not m:
                # Field access after a function call — uncommon; preserve as JSON nav
                current = f"({current})->'{seg}'"
                continue
            fn = m.group(1)
            args = m.group(2)
            if fn == "split":
                # split('sep') → regexp_split_to_array(text, 'sep')
                current = f"regexp_split_to_array({current}, {args.strip()})"
            elif fn == "last":
                # last() → arr[array_length(arr, 1)]
                current = f"({current})[array_length({current}, 1)]"
            elif fn == "replace":
                # replace('from', 'to') → replace(text, 'from', 'to')
                current = f"replace({current}, {args})"
            else:
                logger.warning(
                    "Unsupported function in path: %s in %s — column will be NULL",
                    seg,
                    orig_path,
                )
                # Return NULL rather than malformed SQL. View still materializes;
                # column is NULL until the function is supported. Common unsupported:
                # ofType(Type), conformsTo(profile), iif(cond, a, b), aggregate().
                return FHIRPathExpression(path=orig_path, sql="NULL")
        return FHIRPathExpression(path=orig_path, sql=current)

    def _transpile_where_clause(
        self, fhir_path: str, as_text: bool, context_path: Optional[str]
    ) -> FHIRPathExpression:
        """
        Transpile where() clause like "coding.where(system='http://loinc.org').code"

        Generates a lateral join with jsonb_array_elements

        Args:
            fhir_path: Path with where clause
            as_text: Use ->> for final output
            context_path: Optional context

        Returns:
            FHIRPathExpression with subquery SQL
        """
        # Parse: <array_path>.where(<condition>).<result_path>
        # Match one or more path segments (including nested like "code.coding")
        match = re.match(r"(.+?)\.where\((.+?)\)(?:\.(.+))?", fhir_path)

        if not match:
            logger.warning(f"Could not parse where clause: {fhir_path}")
            return self._transpile_simple_path(fhir_path, as_text, context_path)

        array_path = match.group(1)  # e.g., "coding" or "code.coding"
        condition = match.group(2)  # e.g., "system='http://loinc.org'"
        result_path = match.group(3)  # e.g., "code"

        # Generate unique alias for array element
        self._array_counter += 1
        array_alias = f"elem_{self._array_counter}"

        # Build base path to array
        if context_path:
            base = context_path
        else:
            base = f"{self.resource_alias}.{self.resource_column}::jsonb"

        # Path to array - handle nested paths like "code.coding"
        if "." in array_path:
            # Nested path: navigate to parent, then to array
            path_parts = array_path.split(".")
            for part in path_parts:
                base = f"{base}->'{part}'"
            array_sql = base
        else:
            # Simple path
            array_sql = f"{base}->'{array_path}'"

        # Parse condition (simple equality only for now)
        condition_sql = self._parse_where_condition(condition, array_alias)

        # Bug 10 + Bug 5 fix (issues #11 + #12): trailing .first() in result_path is
        # already implied by LIMIT 1 below. Previously, result_path was passed
        # verbatim, producing SQL like `SELECT elem->'first()'` (literal JSON-key
        # access, always NULL).
        # - `name.where(use='official').first()` → result_path None (Bug 10)
        # - `coding.where(system='X').first().code` → strip prefix (Bug 10)
        # - `coding.where(system='X').code.first()` → strip suffix (Bug 5)
        if result_path == "first()":
            result_path = None
        elif result_path and result_path.startswith("first()."):
            result_path = result_path[len("first().") :]
        elif result_path and result_path.endswith(".first()"):
            result_path = result_path[: -len(".first()")]

        # Build subquery
        if result_path:
            # Extract specific field from matching element
            if as_text:
                select_expr = f"{array_alias}->>'{result_path}'"
            else:
                select_expr = f"{array_alias}->'{result_path}'"

            sql = f"""(
                SELECT {select_expr}
                FROM jsonb_array_elements({array_sql}) AS {array_alias}
                WHERE {condition_sql}
                LIMIT 1
            )""".strip()
        else:
            # Return entire matching element
            sql = f"""(
                SELECT {array_alias}
                FROM jsonb_array_elements({array_sql}) AS {array_alias}
                WHERE {condition_sql}
                LIMIT 1
            )""".strip()

        return FHIRPathExpression(
            path=fhir_path, sql=sql, requires_subquery=True, array_alias=array_alias
        )

    def _parse_where_condition(self, condition: str, elem_alias: str) -> str:
        """
        Parse where() condition to SQL WHERE clause

        Args:
            condition: FHIRPath condition (e.g., "system='http://loinc.org'")
            elem_alias: Alias for array element

        Returns:
            SQL WHERE condition
        """
        # Simple equality: field='value'
        match = re.match(r"(\w+)\s*=\s*'([^']+)'", condition)
        if match:
            field = match.group(1)
            value = match.group(2)
            return "{}->>'{}'  = '{}'".format(elem_alias, field, value)

        # TODO: Support more complex conditions
        logger.warning(f"Unsupported where condition: {condition}")
        return "true"

    def _transpile_first(
        self, fhir_path: str, as_text: bool, context_path: Optional[str]
    ) -> FHIRPathExpression:
        """
        Transpile first() function

        Args:
            fhir_path: Path with .first()
            as_text: Use ->> for output
            context_path: Optional context

        Returns:
            FHIRPathExpression accessing first array element
        """
        # Remove .first() and access [0]
        base_path = fhir_path.replace(".first()", "")

        # Bug 13 fix (issue #12): if a MID-PATH segment is already a known array
        # field, Bug 3's array-position logic already took element 0 there. The
        # prefix resolves to a scalar; .first() is redundant. Adding ->>0 on a
        # scalar produces "operator is not unique" or returns NULL.
        # Example: `clinicalStatus.coding.code.first()` — coding is in ARRAY_FIELDS
        # (mid-path), so prefix is ...->'coding'->0->'code' (first coding's code).
        # vs. `given.first()` (no mid-path arrays) — .first() IS needed to take
        # element 0 of the given[] array.
        # Initial Bug 13 fix checked the LAST segment, which was wrong: it bypassed
        # array-indexing for `given.first()` (regressed patient_demographics in #12).
        segments_no_first = base_path.split(".")
        has_mid_path_array = any(seg in self._ARRAY_FIELDS for seg in segments_no_first[:-1])
        if has_mid_path_array:
            return self._transpile_simple_path(base_path, as_text, context_path)

        # Transpile base path (jsonb result for array indexing)
        base_expr = self._transpile_simple_path(base_path, False, context_path)

        # Bug 7 fix (issue #11): respect as_text. Previously both branches emitted ->0
        # (jsonb). When called from a text context (column rendering, COALESCE for
        # string concat in Bug 8), we need ->>0 to coerce to text. The dead-code
        # if/else made every .first() return jsonb regardless of caller intent.
        if as_text:
            sql = f"({base_expr.sql})->>0"
        else:
            sql = f"({base_expr.sql})->0"

        return FHIRPathExpression(path=fhir_path, sql=sql)

    # Bug 2 fix (issue #11): FHIR R4 [x] choice fields are stored under
    # `<base><Type>` keys (e.g., `deceasedBoolean`, `deceasedDateTime`), not under
    # the bare `deceased` key. The transpiler doesn't know FHIR resource definitions,
    # so we hardcode the choice variants for the fields actually used by current
    # view defs. Patient.deceased[x] is the only one in scope. Extend this map as
    # other view defs add resources with [x] fields (e.g., Observation.value[x],
    # Patient.multipleBirth[x]).
    _CHOICE_FIELDS: Dict[str, List[str]] = {
        "deceased": ["deceasedDateTime", "deceasedBoolean"],
    }

    # FHIR fields that are arrays in the spec — when navigated via simple paths,
    # implicit-first-element semantics apply (Bug 3 + Bug 13). Promoted to
    # class-level (was local to _transpile_simple_path) so _transpile_first can
    # also consult it for the scalar-leaf check.
    _ARRAY_FIELDS = frozenset({"name", "address", "telecom", "identifier", "coding"})

    # Function-call segments in path expressions. Recognized in _transpile_simple_path
    # via _FUNCTION_CALL_RE and dispatched to _apply_function_chain (Bug 4/6, issue #12).
    _FUNCTION_CALL_RE = re.compile(r"^(\w+)\((.*)\)$")

    def _transpile_exists(self, fhir_path: str, context_path: Optional[str]) -> FHIRPathExpression:
        """
        Transpile exists() function to check if field exists and is not null

        Args:
            fhir_path: Path with .exists()
            context_path: Optional context

        Returns:
            FHIRPathExpression with boolean check
        """
        base_path = fhir_path.replace(".exists()", "")

        # Bug 2: choice-type field. Check ANY variant exists.
        if base_path in self._CHOICE_FIELDS and not context_path:
            base = f"{self.resource_alias}.{self.resource_column}::jsonb"
            checks = " OR ".join(
                f"{base}->'{variant}' IS NOT NULL" for variant in self._CHOICE_FIELDS[base_path]
            )
            return FHIRPathExpression(path=fhir_path, sql=f"({checks})")

        base_expr = self._transpile_simple_path(base_path, False, context_path)
        sql = f"({base_expr.sql} IS NOT NULL)"

        return FHIRPathExpression(path=fhir_path, sql=sql)

    def _transpile_count(self, fhir_path: str, context_path: Optional[str]) -> FHIRPathExpression:
        """
        Transpile count() function for arrays

        Args:
            fhir_path: Path with .count()
            context_path: Optional context

        Returns:
            FHIRPathExpression with jsonb_array_length
        """
        base_path = fhir_path.replace(".count()", "")
        base_expr = self._transpile_simple_path(base_path, False, context_path)

        sql = f"jsonb_array_length({base_expr.sql})"

        return FHIRPathExpression(path=fhir_path, sql=sql)

    def _transpile_empty(self, fhir_path: str, context_path: Optional[str]) -> FHIRPathExpression:
        """
        Transpile empty() function to check if value is null or empty

        Args:
            fhir_path: Path with .empty()
            context_path: Optional context

        Returns:
            FHIRPathExpression with null/empty check
        """
        base_path = fhir_path.replace(".empty()", "")
        base_expr = self._transpile_simple_path(base_path, False, context_path)

        sql = f"({base_expr.sql} IS NULL OR {base_expr.sql} = '[]'::jsonb)"

        return FHIRPathExpression(path=fhir_path, sql=sql)

    def _transpile_concatenation(
        self, fhir_path: str, as_text: bool, context_path: Optional[str]
    ) -> FHIRPathExpression:
        """
        Transpile string concatenation using + operator

        Args:
            fhir_path: Path with + operator (e.g., "given.first() + ' ' + family")
            as_text: Use ->> for text output
            context_path: Optional context

        Returns:
            FHIRPathExpression with SQL concatenation using ||
        """
        # Split by + operator
        parts = fhir_path.split(" + ")

        sql_parts = []
        for part in parts:
            part = part.strip()

            # Check if it's a string literal (quoted)
            if part.startswith("'") and part.endswith("'"):
                # Keep string literal as-is
                sql_parts.append(part)
            else:
                # Transpile as FHIRPath expression
                expr = self.transpile(part, as_text=True, context_path=context_path)
                sql_parts.append(f"COALESCE({expr.sql}, '')")

        # Join with SQL concatenation operator ||
        sql = " || ".join(sql_parts)

        return FHIRPathExpression(path=fhir_path, sql=sql)

    def transpile_forEach(
        self, fhir_path: str, column_paths: List[Tuple[str, str]]
    ) -> Tuple[str, str, str]:
        """
        Transpile forEach expression for lateral join

        Args:
            fhir_path: forEach path (e.g., "name" for array iteration)
            column_paths: List of (column_name, fhir_path) to extract from each element

        Returns:
            Tuple of (lateral_join_clause, array_alias, select_columns)
        """
        # Generate unique alias
        self._array_counter += 1
        array_alias = f"foreach_{self._array_counter}"

        # Build path to array
        base = f"{self.resource_alias}.{self.resource_column}::jsonb"
        array_path = f"{base}->'{fhir_path}'"

        # Build lateral join
        lateral_join = f"""
            LEFT JOIN LATERAL jsonb_array_elements({array_path}) AS {array_alias}
            ON true
        """.strip()

        # Build SELECT columns for each path in the forEach context
        select_columns = []
        for col_name, col_path in column_paths:
            # Transpile in context of array element
            expr = self.transpile(col_path, as_text=True, context_path=array_alias)
            select_columns.append(f"{expr.sql} AS {col_name}")

        return lateral_join, array_alias, ", ".join(select_columns)


def create_fhirpath_transpiler(
    resource_alias: str = "v", resource_column: str = "res_text_vc"
) -> FHIRPathTranspiler:
    """
    Factory function to create FHIRPath transpiler

    Args:
        resource_alias: Alias for resource version table
        resource_column: Column with JSONB resource

    Returns:
        Configured FHIRPathTranspiler
    """
    return FHIRPathTranspiler(resource_alias, resource_column)
