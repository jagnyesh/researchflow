"""#242: read the phenotype SQL's predicates from its AST and check them
against a gold case's required predicates.

Each top-level WHERE conjunct must match one canonical shape exactly, with a
single bound parameter in every placeholder position:
  - ("gender", "=", "female")         p.gender = :g
  - ("age", ">", 65)                  EXTRACT(YEAR FROM AGE(CURRENT_DATE,
                                        CAST(p.birth_date AS DATE))) > :a
  - ("condition", "has", "term")      EXISTS(.. condition_simple c WHERE
                                        c.patient_id = p.patient_id AND
                                        (LOWER(<col>) LIKE LOWER(:c) OR ..))
                                        over the oracle's three columns,
                                        with :c bound to '%term%'
  - ("condition", "lacks", "term")    NOT EXISTS(...)
Anything else, including a cohort source other than the bare patient table,
is ("unrecognized", <sql>, None). It is reported as extra, so a narrower or
broader predicate fails the case instead of passing unnoticed.
"""

import re
from typing import Dict, Optional, Set, Tuple

import sqlglot
from sqlglot import exp

Predicate = Tuple[str, str, object]

_PATIENT_TABLE = "sqlonfhir.patient_demographics AS p"
_COMPARISONS = {">": exp.GT, ">=": exp.GTE, "<": exp.LT, "<=": exp.LTE}
# The oracle's condition match (formal_cases._DIABETES_MELLITUS); fewer columns
# is a narrower match than the request.
_CONDITION_COLUMNS = ("code_text", "icd10_display", "snomed_display")


def _sql(node: exp.Expression) -> str:
    return node.sql(dialect="postgres")


def _template(sql: str) -> str:
    return _sql(sqlglot.parse_one(sql, read="postgres"))


_GENDER = _template("p.gender = :x")
_AGE = {
    op: _template(f"EXTRACT(YEAR FROM AGE(CURRENT_DATE, CAST(p.birth_date AS DATE))) {op} :x")
    for op in _COMPARISONS
}
_HAS_CONDITION = _template(
    "EXISTS (SELECT 1 FROM sqlonfhir.condition_simple AS c "
    "WHERE c.patient_id = p.patient_id AND ("
    + " OR ".join(f"LOWER(c.{col}) LIKE LOWER(:x)" for col in _CONDITION_COLUMNS)
    + "))"
)


def _conjuncts(node: exp.Expression):
    if isinstance(node, exp.And):
        yield from _conjuncts(node.left)
        yield from _conjuncts(node.right)
    elif isinstance(node, exp.Paren):
        yield from _conjuncts(node.this)
    else:
        yield node


def _normalized(node: exp.Expression) -> Tuple[str, Optional[str]]:
    """The node's SQL with its one placeholder renamed :x, and that
    placeholder's name; (sql, None) unless there is exactly one name."""
    names = {p.name for p in node.find_all(exp.Placeholder)}
    if len(names) != 1:
        return _sql(node), None
    copy = node.copy()
    for placeholder in copy.find_all(exp.Placeholder):
        placeholder.replace(exp.Placeholder(this="x"))
    return _sql(copy), names.pop()


def _predicate(node: exp.Expression, params: Dict) -> Predicate:
    unrecognized = ("unrecognized", _sql(node), None)
    negated = isinstance(node, exp.Not)
    shape, name = _normalized(node.this if negated else node)
    if name is None or name not in params:
        return unrecognized
    value = params[name]
    if shape == _HAS_CONDITION:
        match = re.fullmatch(r"%([^%_]+)%", str(value))
        if match:
            return ("condition", "lacks" if negated else "has", match.group(1).lower())
    elif not negated and shape == _GENDER:
        return ("gender", "=", str(value).lower())
    elif not negated:
        for op, template in _AGE.items():
            if shape == template:
                return ("age", op, value)
    return unrecognized


def extract_predicates(sql: str, params: Dict) -> Set[Predicate]:
    select = sqlglot.parse_one(sql, read="postgres")
    found = set()
    source = select.args.get("from_")
    if (
        not isinstance(select, exp.Select)
        or select.args.get("with")
        or select.args.get("joins")
        or source is None
        or _sql(source.this) != _PATIENT_TABLE
    ):
        # Filtering in a CTE, join or FROM subquery is outside the checked WHERE.
        found.add(("unrecognized", "cohort source is not the bare patient table", None))
    where = select.args.get("where")
    if where is not None:
        found |= {_predicate(c, params) for c in _conjuncts(where.this)}
    return found


def check_predicates(case, sql: str, params: Dict) -> Tuple[Set[Predicate], Set[Predicate]]:
    """(missing, extra): required predicates absent from the SQL, and SQL
    predicates the case did not require."""
    found = extract_predicates(sql, params)
    required = set(case.required_predicates)
    return required - found, found - required
