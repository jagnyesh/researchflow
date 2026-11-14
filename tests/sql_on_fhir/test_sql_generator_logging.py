"""#468, ADR 0037: SQLGenerator logs say what was built, never the SQL or the values.

Criterion terms are PHI-adjacent (ADR 0036), and bound values belong in the
query, not the log. The generated SQL stays reviewable in the approval record.
"""

import logging
import re

from app.utils.sql_generator import SQLGenerator
from tests.fixtures import RequirementsBuilder as RB

TERM = "zzconditionsentinel"


def _logged_while_generating(caplog):
    reqs = RB.build_requirements(
        inclusion=[
            RB.build_condition("a condition", term=TERM),
            RB.build_demographic("Male patients", term="male"),
            RB.build_demographic("Age > 18", term="age", details="> 18"),
        ],
        exclusion=[RB.build_demographic("Female patients", term="female")],
    )
    with caplog.at_level(logging.DEBUG, logger="app.utils.sql_generator"):
        sql, params = SQLGenerator(use_materialized_views=True).generate_phenotype_sql(
            reqs, count_only=True
        )
    return sql, params, "\n".join(r.getMessage() for r in caplog.records)


def test_logs_carry_no_sql_text_and_no_bound_values(caplog):
    sql, params, logged = _logged_while_generating(caplog)

    assert TERM not in logged
    assert not re.search(r"\b(fe)?male\b", logged, re.IGNORECASE)
    for fragment in ("LIKE", "p.gender", "birth_date", "SELECT", "EXISTS"):
        assert fragment not in logged, fragment
    # The query itself still carries everything.
    assert "p.gender" in sql and any(TERM in str(v) for v in params.values())


def test_logs_still_name_the_bound_parameters(caplog):
    _, params, logged = _logged_while_generating(caplog)

    for name in params:
        assert name in logged, name
