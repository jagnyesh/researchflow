"""#242: read the phenotype SQL's predicates from its AST and check them
against a gold case's required predicates.

Each top-level WHERE conjunct becomes one canonical predicate, with its bound
parameter resolved:
  - ("gender", "=", "female")         p.gender = :g
  - ("age", ">", 65)                  EXTRACT(YEAR FROM AGE(.. birth_date)) > :a
  - ("condition", "has", "term")      EXISTS(.. condition_simple .. LIKE :c)
  - ("condition", "lacks", "term")    NOT EXISTS(...)
Anything else is ("unrecognized", <sql>, None), so an unexpected predicate is
reported as extra instead of passing unnoticed.
"""

from typing import Dict, Set, Tuple

import sqlglot
from sqlglot import exp

Predicate = Tuple[str, str, object]

_COMPARISONS = {exp.EQ: "=", exp.GT: ">", exp.GTE: ">=", exp.LT: "<", exp.LTE: "<="}


def _conjuncts(node: exp.Expression):
    if isinstance(node, exp.And):
        yield from _conjuncts(node.left)
        yield from _conjuncts(node.right)
    elif isinstance(node, exp.Paren):
        yield from _conjuncts(node.this)
    else:
        yield node


def _param(node: exp.Expression, params: Dict):
    placeholder = node if isinstance(node, exp.Placeholder) else node.find(exp.Placeholder)
    return params.get(placeholder.name) if placeholder is not None else None


def _condition_term(subquery: exp.Expression, params: Dict):
    tables = {t.name for t in subquery.find_all(exp.Table)}
    terms = {str(_param(like.expression, params)) for like in subquery.find_all(exp.Like)}
    if tables != {"condition_simple"} or len(terms) != 1:
        return None
    return terms.pop().strip("%").lower()


def _predicate(node: exp.Expression, params: Dict) -> Predicate:
    negated = isinstance(node, exp.Not)
    inner = node.this if negated else node
    if isinstance(inner, exp.Exists):
        term = _condition_term(inner, params)
        if term is not None:
            return ("condition", "lacks" if negated else "has", term)
    elif not negated and type(node) in _COMPARISONS:
        op = _COMPARISONS[type(node)]
        left, value = node.this, _param(node.expression, params)
        if isinstance(left, exp.Column) and left.name == "gender" and op == "=":
            return ("gender", "=", str(value).lower())
        if isinstance(left, exp.Extract) and left.find(exp.Column, bfs=False) is not None:
            if any(c.name == "birth_date" for c in left.find_all(exp.Column)):
                return ("age", op, value)
    return ("unrecognized", node.sql(dialect="postgres"), None)


def extract_predicates(sql: str, params: Dict) -> Set[Predicate]:
    where = sqlglot.parse_one(sql, read="postgres").args.get("where")
    if where is None:
        return set()
    return {_predicate(c, params) for c in _conjuncts(where.this)}


def check_predicates(case, sql: str, params: Dict) -> Tuple[Set[Predicate], Set[Predicate]]:
    """(missing, extra): required predicates absent from the SQL, and SQL
    predicates the case did not require."""
    found = extract_predicates(sql, params)
    required = set(case.required_predicates)
    return required - found, found - required
