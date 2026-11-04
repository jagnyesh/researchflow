"""#225: PHI-bearing values never become log *context*.

The #181/#183 guard keeps exception text out of logs; nothing kept the
researcher's query, the derived requirements, email bodies or a DB URL out of
the message itself. This AST guard fails when one of those names is
interpolated into a logging call anywhere in app/. A count or a set/unset
flag is fine: a name under len() or bool() is not flagged.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PHI_NAMES = {
    "initial_request",
    "natural_language_query",
    "nl_query",
    "requirements",
    "structured_requirements",
    "researcher_email",
    "email_body",
    "email_content",
    "birth_date",
    "birth_date_str",
    "patient_ref",
    "database_url",
    "db_url",
    "hapi_db_url",
    "hapi_url",
    "HAPI_DB_URL",
    "DATABASE_URL",
    "healthcare_db_url",
    "audit_redis_url",
    "redis_url",
    "email",
}
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}


def _is_log_call(node):
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr not in LOG_METHODS:
        return False
    target = node.func.value
    name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
    return name in {"logger", "log", "logging", "_logger", "LOGGER"}


def _phi_refs(node):
    """PHI names referenced in `node`, skipping anything under len() or bool()."""
    found = []
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) in {"len", "bool"}:
            continue
        if isinstance(n, ast.Name) and n.id in PHI_NAMES:
            found.append(n.id)
        elif isinstance(n, ast.Attribute) and n.attr in PHI_NAMES:
            found.append(n.attr)
        elif (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and n.args[0].value in PHI_NAMES
        ):
            found.append(n.args[0].value)
        elif isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant):
            if n.slice.value in PHI_NAMES:
                found.append(n.slice.value)
        stack.extend(ast.iter_child_nodes(n))
    return found


def _leaks(source):
    tree = ast.parse(source)
    out = []
    for node in ast.walk(tree):
        if _is_log_call(node):
            for arg in list(node.args) + [k.value for k in node.keywords]:
                for name in _phi_refs(arg):
                    out.append((node.lineno, name))
    return out


def test_no_phi_bearing_name_is_interpolated_into_a_log_call():
    leaks = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        for line, name in _leaks(path.read_text()):
            leaks.append(f"{path.relative_to(ROOT)}:{line} ({name})")
    assert leaks == []


@pytest.mark.parametrize(
    "snippet",
    [
        'logger.info(f"query: {natural_language_query}")',
        'logger.debug(f"Full requirements: {requirements}")',
        'logger.info("to %s", researcher_info.get("researcher_email"))',
        'self.logger.debug(f"body {email_body}")',
        'logging.warning(f"dob {birth_date_str}")',
        "logger.info(f\"db {state['researcher_email']}\")",
    ],
)
def test_the_guard_catches_each_shape(snippet):
    assert _leaks(snippet), snippet


def test_counts_and_ids_are_allowed():
    assert not _leaks('logger.info(f"{len(requirements)} criteria for {request_id}")')


def test_the_view_script_prints_no_password(monkeypatch, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "create_materialized_views", ROOT / "scripts" / "create_materialized_views.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    shown = module._redacted("postgresql://hapi:s3cr3t-pw@db.internal:5433/hapi")

    assert shown == "db.internal:5433/hapi"
