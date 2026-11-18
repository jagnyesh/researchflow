"""#142: read the gender and age predicates from exploratory (LLM-written)
SQL's AST, for the predicate survival check (ADR 0042).

The formal checker (formal_predicates.py) can't read this SQL: the model
joins tables, inlines literals and writes age as date arithmetic. A predicate
counts only as a top-level WHERE conjunct on a sqlonfhir.patient_demographics
column, with table aliases resolved across FROM and JOINs. Every JOIN must
link to an earlier source on patient_id; otherwise nothing survives, since a
predicate on an unlinked table doesn't restrict the rows counted.
  - ("gender", "=", "female")      <patient>.gender = 'female' (either side)
  - ("age", ">=", 18)              <patient>.birth_date[::date] <=
                                     CURRENT_DATE - INTERVAL '18 years'
  - ("age", "<", 65)               <patient>.birth_date[::date] >
                                     CURRENT_DATE - INTERVAL '65 years'
  - ("age", op, n)                 EXTRACT(YEAR FROM AGE([CURRENT_DATE,]
                                     <patient>.birth_date[::date])) op n
Mirrored comparisons count. The < and >= birth_date forms don't: they are off
by a day for people whose birthday is today. Anything else is ignored: the
survival check asks only whether each stated predicate is present.
"""

from typing import Dict, Optional, Set, Tuple

import sqlglot
from sqlglot import exp

Predicate = Tuple[str, str, object]

_PATIENTS = ("sqlonfhir", "patient_demographics")


def _sources(select: exp.Select) -> Dict[str, Optional[Tuple[str, str]]]:
    """{alias or name: (schema, table)} for each FROM and JOIN source; None
    for a source that isn't a plain table (a subquery, say)."""
    nodes = [select.args["from_"].this] if select.args.get("from_") else []
    nodes += [j.this for j in select.args.get("joins") or []]
    return {n.alias_or_name: (n.db, n.name) if isinstance(n, exp.Table) else None for n in nodes}


def _patient_id_link(node: exp.Expression, joined: str, earlier: Set[str]) -> bool:
    """joined.patient_id = <earlier source>.patient_id, either side."""
    if not isinstance(node, exp.EQ):
        return False
    columns = (node.this, node.expression)
    if not all(isinstance(c, exp.Column) and c.name == "patient_id" for c in columns):
        return False
    tables = {c.table for c in columns}
    return joined in tables and bool((tables - {joined}) & earlier)


def _linked(select: exp.Select) -> bool:
    """Every JOIN links to an earlier source on patient_id, so a predicate on
    any source restricts the rows counted (review finding 2). A comma join, a
    CROSS JOIN, ON TRUE or USING doesn't count."""
    earlier = {select.args["from_"].this.alias_or_name} if select.args.get("from_") else set()
    for join in select.args.get("joins") or []:
        joined, on = join.this.alias_or_name, join.args.get("on")
        if on is None or not any(_patient_id_link(c, joined, earlier) for c in _conjuncts(on)):
            return False
        earlier.add(joined)
    return True


def _on_patients(node: exp.Expression, sources, column: str) -> bool:
    if not isinstance(node, exp.Column) or node.name != column:
        return False
    if node.table:
        return sources.get(node.table) == _PATIENTS
    return list(sources.values()) == [_PATIENTS]


def _conjuncts(node: exp.Expression):
    if isinstance(node, exp.And):
        yield from _conjuncts(node.left)
        yield from _conjuncts(node.right)
    elif isinstance(node, exp.Paren):
        yield from _conjuncts(node.this)
    else:
        yield node


def _gender(node: exp.Expression, sources) -> Optional[Predicate]:
    if not isinstance(node, exp.EQ):
        return None
    for column, value in ((node.this, node.expression), (node.expression, node.this)):
        if (
            _on_patients(column, sources, "gender")
            and isinstance(value, exp.Literal)
            and value.is_string
        ):
            # Exact, not lowercased: = is case-sensitive, and 'FEMALE' matches no row.
            return ("gender", "=", value.this)
    return None


_OPS = {exp.GT: ">", exp.GTE: ">=", exp.LT: "<", exp.LTE: "<="}
_MIRROR = {">": "<", ">=": "<=", "<": ">", "<=": ">="}
# birth_date OP (CURRENT_DATE - N years) as an age bound. Only these two are
# exact for whole-year ages; < and >= are off for people whose birthday is today.
_BIRTH_DATE_TO_AGE = {"<=": ">=", ">": "<"}


def _birth_date(node: exp.Expression, sources) -> bool:
    if isinstance(node, exp.Cast) and node.to.is_type(exp.DataType.Type.DATE):
        node = node.this
    return _on_patients(node, sources, "birth_date")


def _years_ago(node: exp.Expression) -> Optional[int]:
    """N for CURRENT_DATE - INTERVAL 'N years'."""
    if not (isinstance(node, exp.Sub) and isinstance(node.this, exp.CurrentDate)):
        return None
    interval = node.expression
    if (
        isinstance(interval, exp.Interval)
        and isinstance(interval.this, exp.Literal)
        and str(interval.this.this).isdecimal()
        and interval.text("unit").upper() in ("YEAR", "YEARS")
    ):
        return int(interval.this.this)
    return None


def _age_in_years(node: exp.Expression, sources) -> bool:
    """EXTRACT(YEAR FROM AGE([CURRENT_DATE,] birth_date))."""
    if not (isinstance(node, exp.Extract) and node.text("this").upper() == "YEAR"):
        return False
    age = node.expression
    if not (isinstance(age, exp.Anonymous) and age.name.upper() == "AGE"):
        return False
    args = age.expressions
    return (len(args) == 1 or (len(args) == 2 and isinstance(args[0], exp.CurrentDate))) and (
        _birth_date(args[-1], sources)
    )


def _age(node: exp.Expression, sources) -> Optional[Predicate]:
    op = _OPS.get(type(node))
    if op is None:
        return None
    for subject, bound, o in (
        (node.this, node.expression, op),
        (node.expression, node.this, _MIRROR[op]),
    ):
        years = _years_ago(bound)
        if years is not None and o in _BIRTH_DATE_TO_AGE and _birth_date(subject, sources):
            return ("age", _BIRTH_DATE_TO_AGE[o], years)
        if (
            isinstance(bound, exp.Literal)
            and not bound.is_string
            and str(bound.this).isdecimal()
            and _age_in_years(subject, sources)
        ):
            return ("age", o, int(bound.this))
    return None


def extract_predicates(sql: str) -> Set[Predicate]:
    try:
        select = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.SqlglotError:
        # SQL the parser can't read carries no predicate; the case still gets
        # scored, so one bad string can't crash a billed run's summary.
        return set()
    if (
        not isinstance(select, exp.Select)
        or select.args.get("where") is None
        or not _linked(select)
    ):
        return set()
    sources = _sources(select)
    found = set()
    for node in _conjuncts(select.args["where"].this):
        predicate = _gender(node, sources) or _age(node, sources)
        if predicate:
            found.add(predicate)
    return found


def missing_predicates(case, sql: Optional[str]) -> Set[Predicate]:
    """The case's stated predicates that the SQL doesn't carry; all of them
    when there is no SQL (the model refused)."""
    required = set(case.required_predicates)
    return required - extract_predicates(sql) if sql else required
