"""DeliveryAgent writes its citation and notification from templates only (#344).

Both used to fall back to an LLM for "custom" inputs. Every Anthropic client
constructor is patched to raise, so building or calling an LLM client fails
the test.
"""

from unittest.mock import patch

import pytest

from app.agents.delivery_agent import DeliveryAgent


def _raise(*args, **kwargs):
    raise AssertionError("DeliveryAgent constructed an LLM client")


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DELIVERY_PATH", str(tmp_path))
    with (
        patch("anthropic.Anthropic", side_effect=_raise),
        patch("anthropic.AsyncAnthropic", side_effect=_raise),
        patch("langchain_anthropic.ChatAnthropic", side_effect=_raise),
        patch("app.utils.llm_client.ChatAnthropic", side_effect=_raise),
        # Keyless runs never reach ChatAnthropic, so guard the wrapper too.
        patch("app.utils.llm_client.LLMClient.__init__", side_effect=_raise),
    ):
        yield DeliveryAgent()


@pytest.mark.asyncio
async def test_custom_citation_uses_the_template(agent):
    requirements = {
        "study_title": "Diabetes Cohort",
        "principal_investigator": "Dr. Test",
        "irb_number": None,
        "metadata": {"custom_citation": "APA"},
    }

    citation = await agent._generate_citation_info(requirements)

    assert "**Citation Format:**" in citation
    assert "Diabetes Cohort" in citation


@pytest.mark.asyncio
async def test_escalated_notification_uses_the_template(agent):
    delivery_info = {
        "request_id": "REQ-1",
        "location": "/deliveries/REQ-1",
        "cohort_size": 2,
        "data_elements": ["demographics"],
        "escalated": True,
        "custom_message": "please call",
    }

    message = await agent._send_notification("Dr. Test", "pi@example.org", delivery_info)

    assert message.startswith("Dear Dr. Test,")
    assert "REQ-1" in message
    assert "/deliveries/REQ-1" in message
