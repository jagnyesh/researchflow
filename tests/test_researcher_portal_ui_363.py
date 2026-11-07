"""
#363 — the formal portal's interface, driven through ``streamlit.testing``.

Only the external seams are stubbed, at their source modules: the LangGraph
orchestrator (DB + LLM), the DB session behind ``check_delivery_status``,
``get_engine`` and ``FileStorageService``. The page itself runs for real.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

PORTAL = str(Path(__file__).resolve().parents[1] / "app" / "web_ui" / "researcher_portal.py")

EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿⬀-⯿⏩-⏺]")

REQ_ID = "REQ-20261107-9C41D2AA"
EMAIL = "jsmith@hospital.edu"


def _status(state="delivered", **overrides):
    status = {
        "request_id": REQ_ID,
        "current_state": state,
        "current_agent": None,
        "started_at": "2026-11-07T10:00:00",
        "researcher_info": {
            "name": "Dr. Jane Smith",
            "email": EMAIL,
            "department": "Cardiology",
            "irb_number": "IRB-2026-014",
        },
        "agents_involved": [
            {
                "agent": "requirements_agent",
                "task": "validate_requirements",
                "timestamp": "2026-11-07T10:00:05",
            }
        ],
    }
    status.update(overrides)
    return status


def _fakes(status, delivered=True):
    class Orchestrator:
        def __init__(self, *args, **kwargs):
            pass

        async def get_requests_by_researcher(self, email):
            return [dict(status)]

        async def get_request_status(self, request_id):
            return dict(status)

    class Delivery:
        file_list = ["cohort.csv"]
        cohort_size = 1284
        delivery_metadata = {}
        data_elements = ["demographics", "labs"]
        preview_data = None
        preview_qa_report = None

    class Result:
        def scalar_one_or_none(self):
            return Delivery() if delivered else None

    class Session:
        async def execute(self, *args, **kwargs):
            return Result()

    class SessionCM:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *args):
            return False

    class FileStorage:
        def _get_request_directory(self, request_id):
            return Path("/tmp/researchflow-test-nonexistent") / request_id

    return [
        patch("app.langchain_orchestrator.request_facade.LangGraphRequestFacade", Orchestrator),
        patch("app.database.get_engine", lambda *a, **k: MagicMock()),
        patch("app.database.get_db_session", lambda: SessionCM()),
        patch("app.services.file_storage.FileStorageService", FileStorage),
    ]


def _run(status=None, delivered=True, selected=True, email=False, view=False, req_id=REQ_ID):
    patches = _fakes(status or _status(), delivered)
    for p in patches:
        p.start()
    try:
        at = AppTest.from_file(PORTAL, default_timeout=60)
        if selected:
            at.session_state["selected_request"] = req_id
        at.run()
        if email or view:
            at.text_input(key="sidebar_email").set_value(EMAIL).run()
        if view:
            at.button(key=f"view_{REQ_ID}").click().run()
        return at
    finally:
        for p in patches:
            p.stop()


def _all_text(at):
    texts = [m.value for m in at.markdown]
    texts += [c.value for c in at.caption]
    texts += [t.value for t in at.title]
    texts += [h.value for h in at.header] + [h.value for h in at.subheader]
    texts += [b.label for b in at.button]
    texts += [e.label for e in at.expander]
    texts += [t.label for t in at.tabs]
    texts += [m.label for m in at.metric] + [m.value for m in at.metric]
    for kind in (at.success, at.info, at.warning, at.error):
        texts += [a.value for a in kind]
    return [t for t in texts if t]


def _html(at):
    return [m.value for m in at.markdown if m.allow_html]


def test_the_interface_carries_no_emoji():
    for at in (_run(selected=False), _run(), _run(view=True)):
        assert not at.exception
        assert [t for t in _all_text(at) if EMOJI.search(t)] == []


def test_the_interface_copy_has_no_exclamation_or_ai_pitch():
    for at in (_run(selected=False, email=True), _run()):
        text = "\n".join(_all_text(at))
        assert "!" not in text
        assert "AI-powered" not in text
        assert "conversational interface" not in text


def test_researcher_and_agent_text_is_escaped_in_html():
    status = _status(
        researcher_info={
            "name": "<b>Jane</b>",
            "email": EMAIL,
            "department": "<img src=x>",
            "irb_number": "<i>IRB</i>",
        },
        agents_involved=[
            {"agent": "<u>qa</u>", "task": "<script>x</script>", "timestamp": "<s>ts</s>"}
        ],
    )
    for at in (_run(status), _run(status, view=True)):
        assert not at.exception
        html = "\n".join(_html(at))
        for raw in ("<b>Jane</b>", "<img src=x>", "<i>IRB</i>", "<script>", "<u>", "<s>"):
            assert raw not in html
        assert "&lt;b&gt;Jane&lt;/b&gt;" in html
        assert "&lt;i&gt;IRB&lt;/i&gt;" in html
        assert "&lt;u&gt;" in html and "&lt;s&gt;" in html


def test_the_request_id_is_escaped_in_its_stamp():
    at = _run(req_id="<b>REQ</b>")

    stamps = "\n".join(h for h in _html(at) if "rf-stamp" in h)
    assert "<b>REQ</b>" not in stamps
    assert "&lt;b&gt;REQ&lt;/b&gt;" in stamps


def test_the_request_carries_its_accession_stamp():
    for at in (_run(), _run(view=True)):
        stamps = [h for h in _html(at) if "rf-stamp" in h]
        assert stamps, "no accession stamp rendered"
        assert any(REQ_ID in s and "IRB-2026-014" in s for s in stamps)


def test_progress_renders_as_a_stage_ledger():
    at = _run(_status("data_extraction", current_agent="extraction_agent"), delivered=False)

    ledger = "\n".join(h for h in _html(at) if "rf-ledger" in h)
    assert ledger.count('class="rf-done"') == 4
    assert ledger.count('class="rf-current"') == 1
    assert ledger.count('class="rf-pending"') == 3
    assert "Data extraction" in ledger


def test_a_delivered_request_has_every_stage_done():
    at = _run(_status("delivered"))

    ledger = "\n".join(h for h in _html(at) if "rf-ledger" in h)
    assert ledger.count('class="rf-done"') == 8
    assert 'class="rf-current"' not in ledger


def test_states_and_agents_read_as_labels():
    at = _run(_status("qa_validation"), delivered=False)

    values = [m.value for m in at.metric]
    assert "Qa validation" not in values and "qa_validation" not in values
    assert "QA validation" in values
    assert "None" not in values


def test_delivery_shows_the_cohort_as_a_figure():
    at = _run()

    figure = "\n".join(h for h in _html(at) if "rf-figure" in h)
    assert "1,284" in figure


def test_sidebar_markers_keep_their_state_category():
    delivered = _run(selected=False, email=True)
    failed = _run(_status("failed"), selected=False, email=True)

    assert any(":material/check_circle:" in e.label for e in delivered.expander)
    assert any(":material/error:" in e.label for e in failed.expander)
    assert any(REQ_ID in e.label for e in delivered.expander), "full request ID in the sidebar"


def test_submission_does_not_celebrate():
    assert "st.balloons" not in Path(PORTAL).read_text()
