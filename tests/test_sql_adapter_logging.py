"""#468, ADR 0037: SQLonFHIRAdapter logs never carry bound values or SQL text.

The extraction path binds up to 1,000 patient IDs as pid_* parameters.
Only the session factory is stubbed: the log line is the boundary under test.
"""

import logging

from app.adapters.sql_on_fhir import SQLonFHIRAdapter

PATIENT_ID = "synthetic-patient-7f3a"
SQL_MARKER = "sql_text_marker_column"


class _Result:
    def __iter__(self):
        return iter([])


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *args, **kwargs):
        return _Result()


async def test_execute_sql_logs_parameter_names_not_values(caplog):
    adapter = SQLonFHIRAdapter()
    adapter._async_session = _Session

    with caplog.at_level(logging.DEBUG, logger="app.adapters.sql_on_fhir"):
        await adapter.execute_sql(
            f"SELECT {SQL_MARKER} FROM t WHERE id IN (:pid_0, :pid_1)",
            {"pid_0": PATIENT_ID, "pid_1": "synthetic-patient-9b21"},
        )

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "pid_0" in logged and "pid_1" in logged
    assert PATIENT_ID not in logged
    assert SQL_MARKER not in logged
