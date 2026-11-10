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
    "user_input",
    "requirements",
    "structured_requirements",
    "researcher_email",
    "recipients",
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
    "base_url",
    "fhir_server_url",
    "FHIR_SERVER_URL",
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
        for line, name in _leaks(path.read_text(encoding="utf-8")):
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
        'logger.info(f"Initialized FHIR client with base URL: {self.base_url}")',
    ],
)
def test_the_guard_catches_each_shape(snippet):
    assert _leaks(snippet), snippet


def test_counts_and_ids_are_allowed():
    assert not _leaks('logger.info(f"{len(requirements)} criteria for {request_id}")')


@pytest.mark.parametrize(
    "url, shown",
    [
        ("postgresql://hapi:s3cr3t-pw@db.internal:5433/hapi", "db.internal:5433/hapi"),
        ("postgresql+asyncpg://hapi:s3cr3t-pw@db.internal/hapi", "db.internal/hapi"),
        ("postgresql://hapi:s3cr3t-pw@h1:5433,h2:5434/hapi", "h1:5433,h2:5434/hapi"),
    ],
)
def test_the_view_script_prints_no_password(url, shown):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "create_materialized_views", ROOT / "scripts" / "create_materialized_views.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._redacted(url) == shown


def test_fhir_client_init_logs_no_credentials(caplog):
    import asyncio
    import logging
    from app.clients.fhir_client import FHIRClient

    with caplog.at_level(logging.INFO):
        client = FHIRClient(base_url="https://canary_user:canary_secret@fhir.internal:8081/fhir")
        try:
            records = [r.message for r in caplog.records]
            assert any("Initialized FHIR client" in m for m in records)
            for m in records:
                assert "canary_user" not in m
                assert "canary_secret" not in m
                assert "fhir.internal:8081" in m
        finally:
            asyncio.run(client.close())


async def _fhir_init_log(url, caplog):
    """What gets logged while a FHIRClient is built for `url`, lower-cased."""
    import logging
    from app.clients.fhir_client import FHIRClient

    # DEBUG on the client's own logger, so a quieter log call is seen too.
    with caplog.at_level(logging.DEBUG, logger="app.clients.fhir_client"):
        client = FHIRClient(base_url=url)
    await client.close()
    return [r.getMessage().lower() for r in caplog.records]


@pytest.mark.parametrize(
    "url",
    [
        # Each one built a client before #398; urlsplit() or .port rejects it.
        "http://CANARYUSER:CANARY[PASS@fhir.internal:8081/fhir",
        "http://CANARYUSER:CANARYPASS@fhir.internal:99999/fhir",
        "http://CANARYUSER:CANARYPASS@fhir.internal:80a/fhir",
        "https://CANARYUSER:CANARY\N{FULLWIDTH COLON}PASS@fhir.internal/fhir",
        "https://CANARYUSER:CANARYpre/PASS@fhir.internal/fhir",
    ],
)
async def test_a_url_the_log_line_cant_parse_still_builds_a_client(url, caplog):
    lines = await _fhir_init_log(url, caplog)

    assert any("initialized fhir client" in line for line in lines)
    assert not [line for line in lines if "canary" in line]


@pytest.mark.parametrize("delimiter", ["/", "?", "#"])
async def test_a_password_that_cuts_the_url_short_isnt_logged_as_the_host(delimiter, caplog):
    # An unescaped "/", "?" or "#" ends the host part early, so urlsplit reads
    # the username as the host and the password's leading digits as the port.
    url = f"https://CANARYUSER:4711{delimiter}CANARYPASS@fhir.internal/fhir"

    lines = await _fhir_init_log(url, caplog)

    assert any("initialized fhir client" in line for line in lines)
    assert not [line for line in lines if "canary" in line or "4711" in line]


async def test_a_username_read_as_the_scheme_isnt_logged(caplog):
    # With no scheme and a password that starts "//", urlsplit reads the
    # username as the scheme.
    lines = await _fhir_init_log("CANARYUSER://CANARYPASS@fhir.internal/fhir", caplog)

    assert any("initialized fhir client" in line for line in lines)
    assert not [line for line in lines if "canary" in line]


@pytest.mark.parametrize(
    "url",
    [
        # The "@" that ends the credentials isn't a literal "@", so urlsplit
        # reads them as the host, or as the host and port.
        "https://CANARYUSER%3ACANARYPASS%40fhir.internal/fhir",
        "https://CANARYTOKEN%40fhir.internal/fhir",
        "https://CANARYUSER:4711/CANARYPASS%40fhir.internal/fhir",
        "https://CANARYUSER:4711/CANARYPASS%2540fhir.internal/fhir",
        "https://CANARYUSER:4711/CANARYPASS\N{FULLWIDTH COMMERCIAL AT}fhir.internal/fhir",
        "https://CANARYUSER:/CANARYPASS\N{FULLWIDTH COMMERCIAL AT}fhir.internal/fhir",
    ],
)
async def test_credentials_before_an_encoded_at_sign_arent_logged_as_the_host(url, caplog):
    lines = await _fhir_init_log(url, caplog)

    assert any("initialized fhir client" in line for line in lines)
    assert not [line for line in lines if "canary" in line or "4711" in line]


@pytest.mark.parametrize(
    "url, target",
    [
        ("https://fhir.internal/fhir", "https://fhir.internal"),
        ("http://user:secret@hapi_fhir:8080/fhir", "http://hapi_fhir:8080"),
        ("http://[::1]:8081/fhir", "http://::1:8081"),
        # No host at all: nothing of the URL is described.
        ("https://CANARYUSER:CANARYPASS@/fhir", "configured host"),
    ],
)
async def test_the_log_line_names_the_scheme_host_and_port_of_a_plain_url(url, target, caplog):
    lines = await _fhir_init_log(url, caplog)

    assert lines == [f"initialized fhir client for {target}"]
