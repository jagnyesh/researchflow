"""
Unit tests for admin_dashboard.check_delivery_status error UX (issue #77).

The delivery-status check calls the FastAPI backend over HTTP. When the backend
is down (`httpx.ConnectError`), slow (`httpx.TimeoutException`), or fails for any
other reason, a researcher — not a developer — is looking at the dashboard. These
tests pin the contract that:

  * the user-facing ``st.error`` message LEADS with actionable guidance, not a raw
    Python errno / exception string, and
  * the returned status dict distinguishes the three failure classes so callers can
    branch on them.

Pure unit tests: ``httpx.get`` and Streamlit's ``st`` are both mocked, so nothing
touches the network or a live Streamlit runtime.
"""

import sys
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app.web_ui.admin_dashboard as dashboard


REQUEST_ID = "REQ-20260517-A097C5F6"


def _capture_st():
    """Patch the module-level Streamlit handle and return the mock for inspection."""
    return patch.object(dashboard, "st", MagicMock())


def _last_error_message(st_mock) -> str:
    """Extract the single positional string passed to the last st.error(...) call."""
    assert st_mock.error.called, "expected st.error to be called"
    args, _kwargs = st_mock.error.call_args
    assert args, "st.error called without a positional message"
    return args[0]


# --------------------------------------------------------------------------- #
# httpx.ConnectError  →  backend unreachable                                    #
# --------------------------------------------------------------------------- #


def test_connect_error_returns_backend_unreachable_status():
    with (
        _capture_st(),
        patch.object(
            dashboard.httpx, "get", side_effect=httpx.ConnectError("[Errno 61] Connection refused")
        ),
    ):
        result = dashboard.check_delivery_status(REQUEST_ID)
    assert result == {"status": "backend_unreachable"}


def test_connect_error_message_leads_with_guidance_not_errno():
    with (
        _capture_st() as st_mock,
        patch.object(
            dashboard.httpx, "get", side_effect=httpx.ConnectError("[Errno 61] Connection refused")
        ),
    ):
        dashboard.check_delivery_status(REQUEST_ID)
    msg = _last_error_message(st_mock)

    # Leads with guidance, not the developer-readable errno.
    assert not msg.lstrip("⚠️ ").startswith("[Errno")
    assert "Error checking delivery status:" not in msg
    # Actionable: names the server as unreachable and points at a recovery action.
    lower = msg.lower()
    assert "can't reach" in lower or "cannot reach" in lower or "unreachable" in lower
    assert "make run" in lower or "platform" in lower or "backend" in lower
    # Any technical detail is demoted to a parenthetical, not the leading sentence.
    assert msg.index("(") > 0, "technical detail should be inside a trailing parenthetical"


# --------------------------------------------------------------------------- #
# httpx.TimeoutException  →  timeout                                            #
# --------------------------------------------------------------------------- #


def test_timeout_returns_timeout_status():
    with (
        _capture_st(),
        patch.object(dashboard.httpx, "get", side_effect=httpx.TimeoutException("timed out")),
    ):
        result = dashboard.check_delivery_status(REQUEST_ID)
    assert result == {"status": "timeout"}


def test_timeout_message_is_distinct_and_suggests_retry():
    with (
        _capture_st() as st_mock,
        patch.object(dashboard.httpx, "get", side_effect=httpx.TimeoutException("timed out")),
    ):
        dashboard.check_delivery_status(REQUEST_ID)
    msg = _last_error_message(st_mock).lower()
    # "Reachable but slow" framing — distinct from the unreachable message.
    assert "reachable" in msg
    assert "retry" in msg or "refresh" in msg or "try" in msg
    assert not msg.lstrip("⚠️ ").startswith("[errno")


# --------------------------------------------------------------------------- #
# Any other exception  →  unknown (+ support code, truncated detail)            #
# --------------------------------------------------------------------------- #


def test_generic_exception_returns_unknown_status():
    with _capture_st(), patch.object(dashboard.httpx, "get", side_effect=ValueError("boom")):
        result = dashboard.check_delivery_status(REQUEST_ID)
    assert result == {"status": "unknown"}


def test_generic_exception_message_has_support_code_and_truncates_detail():
    long_detail = "x" * 500
    with (
        _capture_st() as st_mock,
        patch.object(dashboard.httpx, "get", side_effect=RuntimeError(long_detail)),
    ):
        dashboard.check_delivery_status(REQUEST_ID)
    msg = _last_error_message(st_mock)

    # Actionable generic guidance, not the raw exception as the leading line.
    assert not msg.startswith(long_detail[:10])
    # A support code the researcher can quote (carries the request id).
    assert REQUEST_ID in msg
    # Technical detail is truncated — the full 500-char blob must NOT be echoed.
    assert long_detail not in msg
    assert msg.count("x") <= 200


# --------------------------------------------------------------------------- #
# Happy path + non-200 unchanged                                               #
# --------------------------------------------------------------------------- #


def test_happy_path_returns_json_and_no_error():
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {"delivered": True, "files": [{"name": "cohort.csv"}]}

    with _capture_st() as st_mock, patch.object(dashboard.httpx, "get", return_value=fake_response):
        result = dashboard.check_delivery_status(REQUEST_ID)

    assert result == {"delivered": True, "files": [{"name": "cohort.csv"}]}
    st_mock.error.assert_not_called()


def test_non_200_returns_not_delivered_without_error():
    fake_response = MagicMock()
    fake_response.status_code = 404

    with _capture_st() as st_mock, patch.object(dashboard.httpx, "get", return_value=fake_response):
        result = dashboard.check_delivery_status(REQUEST_ID)

    assert result == {"delivered": False, "files": []}
    st_mock.error.assert_not_called()


# --------------------------------------------------------------------------- #
# show_download_section: error states must NOT stack a "not yet delivered" box  #
# on top of the friendly error already rendered by check_delivery_status (#77). #
# --------------------------------------------------------------------------- #


def _info_messages(st_mock) -> list:
    return [c.args[0] for c in st_mock.info.call_args_list if c.args]


@pytest.mark.parametrize("status", ["backend_unreachable", "timeout", "unknown"])
def test_download_section_suppresses_not_delivered_box_for_error_states(status):
    with (
        _capture_st() as st_mock,
        patch.object(dashboard, "check_delivery_status", return_value={"status": status}),
    ):
        dashboard.show_download_section(REQUEST_ID)

    # The friendly error was already shown by check_delivery_status; the section
    # must NOT also print the misleading "Data not yet delivered / Current status".
    assert not any(
        "Data not yet delivered" in m for m in _info_messages(st_mock)
    ), f"error state {status!r} should not stack a 'not yet delivered' box"


def test_download_section_still_shows_not_delivered_for_genuine_pending():
    # Legit pending path (non-200 → no 'status' key) keeps the informational box.
    with (
        _capture_st() as st_mock,
        patch.object(
            dashboard, "check_delivery_status", return_value={"delivered": False, "files": []}
        ),
    ):
        dashboard.show_download_section(REQUEST_ID)

    assert any(
        "Data not yet delivered" in m for m in _info_messages(st_mock)
    ), "genuine pending delivery should still surface the status box"
