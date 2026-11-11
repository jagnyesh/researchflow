"""#428: the cached system prompts stay above their model's caching threshold.

Anthropic ignores ``cache_control`` on a system prompt shorter than the model's
minimum. A prompt edited below that length stops caching, and nothing else
fails. ADR 0021 records a silent caching failure of the same kind that ran for
six months.

Each case drives a real ``LLMClient`` call site and reads the model and the
system prompt from the outbound Anthropic SDK call. A call site moved to a
model with a higher threshold therefore fails here too.

The test needs no API key: ``AsyncMessages.create`` is replaced, so no request
reaches Anthropic. Tokens are counted with tiktoken ``cl100k_base``. Sprint 8.2
measured Anthropic's count about 13% higher than tiktoken's (5,850 against
5,185), so ``tiktoken >= threshold`` is the conservative check. The
synthesis-prompt test in ``tests/test_schema_introspection.py`` uses the same
rule.
"""

import os
from unittest.mock import patch

import pytest
import tiktoken
from anthropic.resources.messages.messages import AsyncMessages

from app.utils.llm_client import _ANTHROPIC_CACHE_THRESHOLDS, LLMClient


class _OutboundCallCaptured(Exception):
    """Stops the call at the SDK boundary once its kwargs are recorded."""


@pytest.mark.parametrize(
    "method, args",
    [
        ("extract_requirements", ([{"role": "user", "message": "diabetes cohort"}], {})),
        ("extract_medical_concepts", ("patients with diabetes",)),
        ("extract_medical_concepts_batch", (["patients with diabetes", "on metformin"],)),
    ],
    ids=["extract_requirements", "extract_medical_concepts", "extract_medical_concepts_batch"],
)
@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-for-mock"})
async def test_cached_system_prompt_clears_its_models_caching_threshold(method, args):
    captured = {}

    async def capture_create(self, **kwargs):
        captured.update(kwargs)
        raise _OutboundCallCaptured

    with patch.object(AsyncMessages, "create", new=capture_create):
        with pytest.raises(_OutboundCallCaptured):
            await getattr(LLMClient(), method)(*args)

    model = captured["model"]
    families = [family for family in _ANTHROPIC_CACHE_THRESHOLDS if family in model]
    assert len(families) == 1, f"no single caching threshold is recorded for {model}"
    threshold = _ANTHROPIC_CACHE_THRESHOLDS[families[0]]

    system = captured["system"]
    assert system[-1].get("cache_control") == {"type": "ephemeral"}
    tokens = len(
        tiktoken.get_encoding("cl100k_base").encode("".join(block["text"] for block in system))
    )
    assert tokens >= threshold, (
        f"{method} sends a {tokens}-token system prompt to {model}, below its "
        f"{threshold}-token caching threshold; cache_control would be a silent no-op"
    )
