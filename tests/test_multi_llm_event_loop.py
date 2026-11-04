"""#275: a slow secondary-provider call must not block the event loop.

aisuite's client is synchronous. The provider is stubbed with a blocking sleep,
the way a slow Ollama/OpenAI round trip behaves.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.utils.multi_llm_client import MultiLLMClient


class _SlowProvider:
    def __init__(self, seconds: float):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._seconds = seconds

    def _create(self, **_kwargs):
        time.sleep(self._seconds)
        message = SimpleNamespace(content="ok")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.mark.asyncio
async def test_other_coroutines_run_while_a_secondary_call_is_in_flight(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    client = MultiLLMClient(secondary_provider="ollama")
    client.aisuite_client = _SlowProvider(seconds=0.5)

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    ticking = asyncio.create_task(ticker())
    try:
        result = await client.complete("hello", task_type="calendar")
    finally:
        ticking.cancel()

    assert result == "ok"
    # A blocked loop would let the ticker run at most once (~0 ticks in 0.5 s).
    assert ticks >= 5, f"event loop was blocked: only {ticks} ticks during a 0.5 s call"
