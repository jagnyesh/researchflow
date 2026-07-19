"""
Regression tests for issue #35 — formal portal download UI unreachable after refresh.

Bug: in a fresh browser session the sidebar's "View Details" button set only
``st.session_state.modal_request``. The "📋 Request Details" tab renders off
``st.session_state.selected_request``, which was set ONLY on new-request
submission. A returning researcher who clicks "View Details" therefore landed
on the tab's empty state ("Select a request from the sidebar to view details")
with no path to the download UI.

These tests drive the real ``researcher_portal.py`` via ``streamlit.testing``.
Only genuine external dependencies are mocked at their source modules:
  * the LangGraph orchestrator (network/DB + LLM),
  * the DB session used by ``check_delivery_status``,
  * ``get_engine`` (avoids real engine/env parsing),
  * ``FileStorageService`` (file-size probe).
The session-state wiring under test is exercised in the real code path.
"""

import os
from pathlib import Path

import pytest
from unittest.mock import patch, MagicMock

from streamlit.testing.v1 import AppTest


PORTAL_PATH = str(Path(__file__).resolve().parents[1] / "app" / "web_ui" / "researcher_portal.py")

REQ_ID = "REQ-20260512-24FB63E0"
RESEARCHER_EMAIL = "jsmith@hospital.edu"

_STATUS = {
    "request_id": REQ_ID,
    "current_state": "delivered",
    "current_agent": None,
    "started_at": "2026-05-12T10:00:00",
    "researcher_info": {
        "name": "Dr. Jane Smith",
        "email": RESEARCHER_EMAIL,
        "department": "Cardiology",
        "irb_number": "IRB-2024-001",
    },
    "agents_involved": [],
}

EMPTY_STATE_MSG = "Select a request from the sidebar to view details"
DOWNLOAD_READY_MSG = "Your data is ready for download!"


class _FakeOrchestrator:
    """Stand-in for LangGraphRequestFacade — no network, no DB, no LLM."""

    def __init__(self, *args, **kwargs):
        pass

    async def get_requests_by_researcher(self, email):
        return [dict(_STATUS)]

    async def get_request_status(self, request_id):
        return dict(_STATUS)


class _FakeDelivery:
    """Mimics a DataDelivery ORM row for a delivered request."""

    file_list = ["cohort.csv"]
    cohort_size = 42
    delivery_metadata = {}
    data_elements = ["demographics", "labs"]
    preview_data = None
    preview_qa_report = None


class _FakeResult:
    def scalar_one_or_none(self):
        return _FakeDelivery()


class _FakeSession:
    async def execute(self, *args, **kwargs):
        return _FakeResult()


class _FakeSessionCM:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, *args):
        return False


def _fake_get_db_session():
    return _FakeSessionCM()


class _FakeFileStorage:
    def _get_request_directory(self, request_id):
        # Non-existent path -> check_delivery_status computes size 0.0 (handled).
        return Path("/tmp/researchflow-test-nonexistent") / request_id


def _make_app():
    """Build an AppTest for the real portal with external seams mocked."""
    at = AppTest.from_file(PORTAL_PATH, default_timeout=60)
    return at


def _run_with_mocks(steps):
    """
    Run the portal under mocked external seams. ``steps(at)`` performs the
    interaction and returns the AppTest for assertions. Patches are applied at
    the SOURCE modules so the script's ``from x import y`` picks them up.
    """
    with (
        patch(
            "app.langchain_orchestrator.request_facade.LangGraphRequestFacade",
            _FakeOrchestrator,
        ),
        patch("app.database.get_engine", lambda *a, **k: MagicMock()),
        patch("app.database.get_db_session", _fake_get_db_session),
        patch("app.services.file_storage.FileStorageService", _FakeFileStorage),
    ):
        at = _make_app()
        at.run()
        return steps(at)


def _enter_email(at):
    at.text_input(key="sidebar_email").set_value(RESEARCHER_EMAIL).run()
    return at


def _tab_shows_empty_state(at):
    return any(EMPTY_STATE_MSG in (i.value or "") for i in at.info)


def _tab_shows_download_ui(at):
    if any(DOWNLOAD_READY_MSG in (s.value or "") for s in at.success):
        return True
    return any("Download Options" in (m.value or "") for m in at.markdown)


class TestDownloadUiReachability:
    def test_empty_state_before_any_selection(self):
        """Control: fresh session + email, no click -> tab shows empty state."""

        def steps(at):
            _enter_email(at)
            assert _tab_shows_empty_state(at), "expected the Details-tab empty state"
            assert not _tab_shows_download_ui(at)
            return at

        _run_with_mocks(steps)

    def test_view_details_sets_selected_request(self):
        """Core regression: clicking View Details must set selected_request."""

        def steps(at):
            _enter_email(at)
            at.button(key=f"view_{REQ_ID}").click().run()
            assert (
                at.session_state["selected_request"] == REQ_ID
            ), "View Details must set selected_request so the Details tab resolves"
            return at

        _run_with_mocks(steps)

    def test_view_details_makes_download_ui_reachable(self):
        """Acceptance #1/#2: after View Details the Details tab renders the
        download UI, not the dead-end empty state."""

        def steps(at):
            _enter_email(at)
            at.button(key=f"view_{REQ_ID}").click().run()
            assert not _tab_shows_empty_state(
                at
            ), "Details tab still on empty state after View Details (dead pointer)"
            assert _tab_shows_download_ui(
                at
            ), "download UI not reachable in Details tab after View Details"
            return at

        _run_with_mocks(steps)

    def test_same_session_submit_flow_still_resolves(self):
        """Acceptance #3 (proxy): the submit handler sets the same session key;
        a set selected_request resolves the tab to the download UI (no
        regression to the submit->download path, which uses the same seam)."""

        def steps(at):
            at.session_state["selected_request"] = REQ_ID
            at.run()
            assert not _tab_shows_empty_state(at)
            assert _tab_shows_download_ui(at)
            return at

        _run_with_mocks(steps)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
