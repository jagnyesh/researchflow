"""#436: the portal's stage ledger and status banner read the state registry."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_researcher_portal_download_ui import (
    PORTAL_PATH,
    REQ_ID,
    _FakeSessionCM,
    _STATUS,
    _enter_email,
)

RAW_ERROR = "Traceback: secret-failure-detail"


class _NotDeliveredResult:
    def scalar_one_or_none(self):
        return None


class _Session:
    async def execute(self, *a, **k):
        return _NotDeliveredResult()


class _CM(_FakeSessionCM):
    async def __aenter__(self):
        return _Session()


def _run(state):
    status = {**_STATUS, "current_state": state, "error_message": RAW_ERROR}

    class Facade:
        def __init__(self, *a, **k):
            pass

        async def get_requests_by_researcher(self, email):
            return [dict(status)]

        async def get_request_status(self, request_id):
            return dict(status)

    with (
        patch("app.langchain_orchestrator.request_facade.LangGraphRequestFacade", Facade),
        patch("app.database.get_engine", lambda *a, **k: MagicMock()),
        patch("app.database.get_db_session", lambda: _CM()),
    ):
        at = AppTest.from_file(PORTAL_PATH, default_timeout=60)
        at.run()
        _enter_email(at)
        at.session_state["selected_request"] = REQ_ID
        at.run()
    assert not at.exception
    return at


def _ledger(at):
    html = " ".join(m.value for m in at.markdown if '<ol class="rf-ledger"' in (m.value or ""))
    return tuple(html.count(f'<li class="rf-{c}"') for c in ("done", "current", "pending"))


def _banner(at):
    return [e.value for e in [*at.info, *at.warning, *at.error]]


def test_complete_request_shows_every_stage_done():
    done, current, pending = _ledger(_run("complete"))
    assert done > 0 and current == 0 and pending == 0


def test_review_gate_marks_earlier_done_and_says_waiting():
    at = _run("phenotype_review")
    done, current, pending = _ledger(at)
    assert done > 0 and current == 1
    assert any("Waiting for review" in b for b in _banner(at))
    assert not any("In progress" in b for b in _banner(at))


@pytest.mark.parametrize("state", ["error", "qa_failed"])
def test_failed_request_shows_fixed_failure_text(state):
    at = _run(state)
    assert [e.value for e in at.error] == ["The request did not complete. Contact support for help"]
    assert not any("In progress" in b for b in _banner(at))
    assert RAW_ERROR not in str(at.main)
