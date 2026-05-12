"""Sprint 8.1 #29 — portal:formal / portal:exploratory tags on @traceable decorators.

Smoke test: each site that should be tagged with its portal must literally
contain the portal-tag string in its source. We inspect the file text rather
than reach into the @traceable wrapper at runtime because langsmith's
decorator metadata access varies across SDK versions and we want this test
to keep working regardless.

Pulled into a dedicated module rather than a fixture-rich integration test
because the regression we're guarding against ("a refactor silently drops a
portal tag") is best caught by a tight string-level assertion that runs in
milliseconds and has zero dependencies.

Reference: DECISIONS.md "Sprint 8.1 — LangSmith is source-of-truth for LLM
cost; explicit portal tags promote domain language into trace data."
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


FORMAL_SITES = [
    "app/agents/base_agent.py",
    "app/agents/requirements_agent.py",
    "app/agents/phenotype_agent.py",
    "app/agents/calendar_agent.py",
    "app/agents/extraction_agent.py",
    "app/agents/qa_agent.py",
    "app/agents/delivery_agent.py",
]


EXPLORATORY_SITES = [
    "app/services/feasibility_service.py",
    "app/services/query_interpreter.py",  # interpret_query needs @traceable added
]


@pytest.mark.parametrize("file_path", FORMAL_SITES)
def test_formal_site_has_portal_tag(file_path):
    """Each formal-portal @traceable site must declare the 'portal:formal' tag."""
    content = (REPO_ROOT / file_path).read_text()
    assert "portal:formal" in content, (
        f"{file_path}: source is missing the 'portal:formal' tag string. "
        f"Add it to the @traceable decorator's tags list. "
        f"See Sprint 8.1 ADR in DECISIONS.md."
    )


@pytest.mark.parametrize("file_path", EXPLORATORY_SITES)
def test_exploratory_site_has_portal_tag(file_path):
    """Each exploratory-portal @traceable site must declare the 'portal:exploratory' tag."""
    content = (REPO_ROOT / file_path).read_text()
    assert "portal:exploratory" in content, (
        f"{file_path}: source is missing the 'portal:exploratory' tag string. "
        f"Add it to the @traceable decorator's tags list (or add the "
        f"decorator itself if absent). See Sprint 8.1 ADR in DECISIONS.md."
    )


def test_query_interpreter_has_traceable_decorator():
    """query_interpreter.interpret_query gains an @traceable in this issue.

    Before #29, only MultiLLMClient.complete (called via self.llm_client) was
    traced, but that wrapper is portal-agnostic. We need a root-level
    @traceable on interpret_query so cost-telemetry can find exploratory
    queries by tag and aggregate child runs into the query's total cost.
    """
    content = (REPO_ROOT / "app/services/query_interpreter.py").read_text()
    assert "@traceable" in content, (
        "app/services/query_interpreter.py: no @traceable decorator found. "
        "Sprint 8.1 #29 adds one to interpret_query with the "
        "'portal:exploratory' tag."
    )
