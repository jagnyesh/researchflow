"""#99 regression — Opus 4.7+/Sonnet 5/Fable 5 REMOVED the `temperature` param:
any value (including 0.0) returns 400 "`temperature` is deprecated for this
model." LLMClient is the Anthropic-boundary wrapper, so it must OMIT temperature
for those models while still forwarding it for Sonnet 4.6 / Haiku 4.5.

These assert at the kwargs boundary (what reaches ChatAnthropic), the layer where
the Sprint 8.2 lesson says third-party-quirk correctness must be verified.
"""

from app.utils.llm_client import (
    _accepts_temperature,
    _chat_anthropic_kwargs,
)


class TestAcceptsTemperature:
    def test_older_models_accept_temperature(self):
        assert _accepts_temperature("claude-sonnet-4-6") is True
        assert _accepts_temperature("claude-haiku-4-5") is True

    def test_newer_models_reject_temperature(self):
        # These 400 on any temperature value — must be omitted, not fixed.
        assert _accepts_temperature("claude-opus-4-8") is False
        assert _accepts_temperature("claude-opus-4-7") is False
        assert _accepts_temperature("claude-sonnet-5") is False
        assert _accepts_temperature("claude-fable-5") is False

    def test_date_suffixed_form_of_a_rejecting_model_is_still_rejected(self):
        # Family-prefix match, not exact id: a future dated snapshot must not
        # slip through and 400 at the wire.
        assert _accepts_temperature("claude-opus-4-8-20260101") is False

    def test_accepting_neighbours_are_not_caught_by_the_prefix(self):
        # The prefixes must NOT strip temperature from 4.6-family models, which
        # still accept it — that would break the production Sonnet 4.6 path.
        assert _accepts_temperature("claude-opus-4-6") is True
        assert _accepts_temperature("claude-sonnet-4-6") is True
        assert _accepts_temperature("claude-sonnet-4-5") is True


class TestChatAnthropicKwargs:
    def test_temperature_forwarded_for_sonnet_4_6(self):
        kwargs = _chat_anthropic_kwargs(
            model="claude-sonnet-4-6", api_key="k", temperature=0.0, max_tokens=4096
        )
        assert kwargs["temperature"] == 0.0
        assert kwargs["model"] == "claude-sonnet-4-6"
        assert kwargs["max_tokens"] == 4096

    def test_temperature_omitted_for_opus_4_8(self):
        # The bug: passing temperature=0.0 to Opus 4.8 returned 400. The fix is
        # to drop the key entirely, not lower the value.
        kwargs = _chat_anthropic_kwargs(
            model="claude-opus-4-8", api_key="k", temperature=0.0, max_tokens=4096
        )
        assert "temperature" not in kwargs
        assert kwargs["model"] == "claude-opus-4-8"
        assert kwargs["max_tokens"] == 4096
