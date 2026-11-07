"""
#362 — the exploratory portal's interface, driven through ``streamlit.testing``.

Only the two external calls are stubbed: intent detection (an LLM call) and the
feasibility check (LLM synthesis + database). The page, its session state and
its message rendering run for real.
"""

import re
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.portal_urls import FORMAL_PORTAL_URL
from app.services.conversation_manager import ConversationManager, UserIntent
from app.services.feasibility_service import FeasibilityService

NOTEBOOK = str(Path(__file__).resolve().parents[1] / "app" / "web_ui" / "research_notebook.py")

EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿⬀-⯿⏩-⏺]")

OK_RESULT = {
    "status": "ok",
    "estimated_cohort": 1284,
    "generated_sql": "SELECT COUNT(DISTINCT p.patient_id) FROM sqlonfhir.patient_demographics p",
    "filter_summary": "Counts women with hypertension younger than 65",
    "execution_time_ms": 12.4,
    "batch_anchor_ts": "2026-11-07T03:00:00",
    "time_period": {},
}


def _app() -> AppTest:
    return AppTest.from_file(NOTEBOOK, default_timeout=60)


def _all_text(at: AppTest) -> list:
    texts = [m.value for m in at.markdown]
    texts += [c.value for c in at.caption]
    texts += [t.value for t in at.title]
    texts += [h.value for h in at.header] + [h.value for h in at.subheader]
    texts += [b.label for b in at.button]
    texts += [i.placeholder for i in at.chat_input]
    texts += [e.label for e in at.expander]
    return texts


def _ask(at: AppTest, question: str, result: dict) -> AppTest:
    async def intent(self, text):
        return UserIntent.QUERY

    async def check(self, query_intent, natural_language_query=None):
        return dict(result)

    async def close(self):
        return None

    with (
        patch.object(ConversationManager, "detect_intent", intent),
        patch.object(FeasibilityService, "execute_feasibility_check", check),
        patch.object(FeasibilityService, "close", close),
    ):
        at.chat_input[0].set_value(question).run()
    return at


def test_user_text_is_never_rendered_as_html():
    at = _app()
    at.session_state["messages"] = [{"role": "user", "content": "<b>hi</b>"}]
    at.run()

    assert not at.exception
    assert not [m.value for m in at.markdown if m.allow_html and "<b>hi</b>" in m.value]


def test_the_interface_carries_no_emoji():
    at = _app().run()

    assert not at.exception
    assert [t for t in _all_text(at) if EMOJI.search(t or "")] == []


def test_the_canned_replies_carry_no_emoji():
    manager = ConversationManager.__new__(ConversationManager)

    assert not EMOJI.search(manager.get_introduction())
    assert not EMOJI.search(manager.get_help_message())


def test_the_formal_portal_is_pointed_to_once():
    at = _app().run()

    assert sum(t.count(FORMAL_PORTAL_URL) for t in _all_text(at)) == 1


def test_a_count_renders_as_a_figure_with_its_anchor():
    at = _ask(_app().run(), "Women with hypertension under 65", OK_RESULT)

    assert not at.exception
    text = "\n".join(_all_text(at))
    assert "1,284" in text
    assert "Data as of 2026-11-07 03:00:00" in text
    assert "Counts women with hypertension younger than 65" in text


def test_every_result_keeps_its_own_sql():
    first = dict(OK_RESULT, generated_sql="SELECT COUNT(*) FROM sqlonfhir.condition_simple")
    at = _ask(_app().run(), "Patients with any condition", first)
    at = _ask(at, "Women with hypertension under 65", OK_RESULT)

    shown = [c.value for c in at.code]
    assert first["generated_sql"] in shown
    assert OK_RESULT["generated_sql"] in shown


def test_an_error_still_never_renders_a_number():
    error = {
        "status": "error",
        "explanation": "Lists patient names",
        "reason": "non-aggregate select item",
        "rejected_sql": "SELECT family_name FROM sqlonfhir.patient_demographics",
    }
    at = _ask(_app().run(), "List the patients", error)

    assert not at.exception
    text = "\n".join(_all_text(at))
    assert "could not be run" in text
    assert not re.search(r"\d[\d,]* patients", text)
