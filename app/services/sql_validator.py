"""SQL Validator — deterministic gate for LLM-synthesized exploratory SQL.

Sprint 6.7 #91 tracer subset of the default-deny rule set (ADR 0028 decision 4):
sqlglot parse (postgres dialect), exactly one statement, SELECT-only, table
references restricted to the 7 sqlonfhir views. #95 extends this to the full
8-rule set (column existence, aggregate-only + dimension allowlist, function
allowlist, LIMIT injection + statement timeout, EXPLAIN dry-run).

Every violation message names the rule broken — #96's retry loop appends the
text to the resynthesis prompt, so the message is part of the contract.
"""

import logging
from dataclasses import dataclass, field
from typing import List

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

logger = logging.getLogger(__name__)

SCHEMA_NAME = "sqlonfhir"

# The 7 production views. #94 replaces this hardcoded set with live
# information_schema introspection (single source of truth for validator
# AND the synthesis prompt's schema block).
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


@dataclass
class ValidationResult:
    valid: bool
    violations: List[str] = field(default_factory=list)


class SQLValidationError(Exception):
    """Synthesized SQL failed validation. #96 replaces raise-to-caller with the
    honest-error variant; until then callers must not swallow this into a 0."""

    def __init__(self, violations: List[str]):
        self.violations = violations
        super().__init__("; ".join(violations))


class SQLValidator:
    """Default-deny validation of synthesized SQL before execution."""

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

        # CTE aliases are query-local names, not tables; their INNER table refs
        # are still scanned below, so laundering through a CTE is still caught.
        cte_aliases = {cte.alias for cte in stmt.find_all(exp.CTE)}

        violations = []
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

        if violations:
            logger.info("SQL validation rejected query: %s", violations)
        return ValidationResult(valid=not violations, violations=violations)
