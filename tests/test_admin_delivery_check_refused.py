"""
Issue #405: the admin dashboard must not report "not delivered" when the delivery
check was refused.

``check_delivery_status`` calls ``GET /research/{id}/delivery`` without credentials;
the route requires an authenticated user, so the API answers 401. The dashboard used
to turn every non-200 into ``{"delivered": False, "files": []}``, which the modal
rendered as "Data not yet delivered", indistinguishable from a request that really
is undelivered (the #76 silent-failure class).

These tests drive the real ``show_download_section`` through Streamlit AppTest and
assert at the HTTP boundary: ``httpx.get`` returns a real ``httpx.Response`` and
nothing between it and the rendered page is mocked.

404 is deliberately unchanged. The route returns 404 for "request not visible to
this user" and for "complete but no delivery record"; both mean there is nothing to
deliver, so "not delivered" is a true answer there.
"""

import httpx
import pytest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

REQUEST_ID = "REQ-20260517-A097C5F6"
URL = f"http://localhost:8000/research/{REQUEST_ID}/delivery"
NOT_DELIVERED = "Data not yet delivered"


def _response(status: int, **body) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("GET", URL))


def _download_section_app(request_id: str):
    from app.web_ui.admin_dashboard import show_download_section

    show_download_section(request_id)


def _render(response: httpx.Response) -> AppTest:
    with patch("httpx.get", return_value=response):
        at = AppTest.from_function(_download_section_app, args=(REQUEST_ID,), default_timeout=30)
        at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _text(at: AppTest) -> str:
    parts = [
        e.value for els in (at.error, at.info, at.success, at.warning, at.markdown) for e in els
    ]
    return "\n".join(parts)


def test_401_renders_could_not_check_and_never_not_delivered():
    at = _render(_response(401, detail="Authentication required"))

    assert len(at.error) == 1
    msg = at.error[0].value
    assert "couldn't check delivery status" in msg.lower()
    assert "authentication required" in msg.lower()
    assert NOT_DELIVERED not in _text(at)


@pytest.mark.parametrize("status", [403, 422, 500, 503])
def test_other_non_200_non_404_renders_could_not_check(status):
    at = _render(_response(status, detail="internal detail that must not leak"))

    assert len(at.error) == 1
    msg = at.error[0].value
    assert "couldn't check delivery status" in msg.lower()
    assert str(status) in msg
    assert REQUEST_ID in msg  # support code the admin can quote
    assert "internal detail" not in _text(at)  # PHI-safe: no response body echoed (#183)
    assert NOT_DELIVERED not in _text(at)


def test_200_delivered_renders_delivery_state():
    at = _render(
        _response(
            200,
            delivered=True,
            cohort_size=42,
            data_elements=["demographics"],
            files=[],
        )
    )

    assert not at.error
    assert any("Data ready for download" in s.value for s in at.success)


def test_200_undelivered_renders_not_delivered():
    at = _render(_response(200, delivered=False, current_state="phenotype_review"))

    assert not at.error
    assert any(NOT_DELIVERED in i.value for i in at.info)


def test_404_still_renders_not_delivered_without_error():
    at = _render(_response(404, detail="No delivery record found"))

    assert not at.error
    assert any(NOT_DELIVERED in i.value for i in at.info)
