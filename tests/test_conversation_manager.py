"""
Tests for ConversationManager hybrid intent detection

Tests both pattern matching (fast path) and LLM fallback (slow path)
"""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from langsmith.run_helpers import get_current_run_tree, tracing_context

from app.services.conversation_manager import ConversationManager, UserIntent


@pytest.mark.asyncio
async def test_pattern_matching_fast_path():
    """Test that simple intents use pattern matching (fast)"""
    cm = ConversationManager()

    # These should use pattern matching (no LLM call)
    assert await cm.detect_intent("hello") == UserIntent.GREETING
    assert await cm.detect_intent("what can you do?") == UserIntent.HELP
    assert await cm.detect_intent("yes") == UserIntent.CONFIRMATION
    assert await cm.detect_intent("what's the status?") == UserIntent.STATUS_CHECK

    # Verify mostly pattern matches
    stats = cm.get_stats()
    assert stats["pattern_matches"] > 0
    assert stats["llm_percentage"] < 50  # Most should be pattern-matched


@pytest.mark.asyncio
async def test_query_keywords_detected():
    """Test that query keywords are detected correctly"""
    cm = ConversationManager()

    # These should match query patterns (pattern matching)
    assert await cm.detect_intent("how many patients are available?") == UserIntent.QUERY
    assert await cm.detect_intent("show me diabetic patients") == UserIntent.QUERY
    assert await cm.detect_intent("give me count of patients") == UserIntent.QUERY
    assert await cm.detect_intent("find female patients") == UserIntent.QUERY
    assert await cm.detect_intent("count of patients with diabetes") == UserIntent.QUERY


@pytest.mark.asyncio
async def test_query_patterns_prioritized_over_help():
    """Test that query patterns are prioritized over help keywords"""
    cm = ConversationManager()

    # "how many" should match QUERY, not HELP
    intent = await cm.detect_intent("how many patients with diabetes?")
    assert intent == UserIntent.QUERY

    # "how do i" should match HELP
    intent = await cm.detect_intent("how do i use this?")
    assert intent == UserIntent.HELP


@pytest.mark.asyncio
async def test_breakdown_query_detected():
    """Test that breakdown queries are detected as QUERY"""
    cm = ConversationManager()

    # The original failing case
    intent = await cm.detect_intent("how many patients broken down by age and gender?")
    assert intent == UserIntent.QUERY

    # Similar breakdown queries
    intent = await cm.detect_intent("give me breakdown by gender")
    assert intent == UserIntent.QUERY


@pytest.mark.asyncio
async def test_negation_triggers_llm():
    """Test that negative context triggers LLM fallback"""
    cm = ConversationManager()

    # Negations should trigger LLM
    await cm.detect_intent("I don't want help")

    # Check that LLM was used
    stats = cm.get_stats()
    assert stats["llm_fallbacks"] > 0


@pytest.mark.asyncio
async def test_greeting_detection():
    """Test greeting detection"""
    cm = ConversationManager()

    # Simple greetings
    assert await cm.detect_intent("hi") == UserIntent.GREETING
    assert await cm.detect_intent("hello") == UserIntent.GREETING
    assert await cm.detect_intent("hey") == UserIntent.GREETING

    # Short greeting phrases
    assert await cm.detect_intent("good morning") == UserIntent.GREETING


@pytest.mark.asyncio
async def test_help_detection():
    """Test help detection"""
    cm = ConversationManager()

    # Help requests
    assert await cm.detect_intent("what can you do?") == UserIntent.HELP
    assert await cm.detect_intent("help me") == UserIntent.HELP
    assert await cm.detect_intent("how do i use this?") == UserIntent.HELP
    assert await cm.detect_intent("how can i get started?") == UserIntent.HELP


@pytest.mark.asyncio
async def test_confirmation_detection():
    """Test confirmation detection"""
    cm = ConversationManager()

    # Confirmations
    assert await cm.detect_intent("yes") == UserIntent.CONFIRMATION
    assert await cm.detect_intent("proceed") == UserIntent.CONFIRMATION
    assert await cm.detect_intent("go ahead") == UserIntent.CONFIRMATION
    assert await cm.detect_intent("confirm") == UserIntent.CONFIRMATION


@pytest.mark.asyncio
async def test_status_check_detection():
    """Test status check detection"""
    cm = ConversationManager()

    # Status checks
    assert await cm.detect_intent("what's the status?") == UserIntent.STATUS_CHECK
    assert await cm.detect_intent("when will it be ready?") == UserIntent.STATUS_CHECK
    assert await cm.detect_intent("how long will this take?") == UserIntent.STATUS_CHECK


@pytest.mark.asyncio
async def test_is_confirmation():
    """Test is_confirmation helper method"""
    cm = ConversationManager()

    # Should be confirmations
    assert await cm.is_confirmation("yes") is True
    assert await cm.is_confirmation("proceed") is True

    # Should not be confirmations
    assert await cm.is_confirmation("no") is False
    assert await cm.is_confirmation("show me patients") is False


@pytest.mark.asyncio
async def test_is_rejection():
    """Test is_rejection helper method"""
    cm = ConversationManager()

    # Should be rejections
    assert await cm.is_rejection("no") is True
    assert await cm.is_rejection("cancel") is True

    # Should not be rejections
    assert await cm.is_rejection("yes") is False


@pytest.mark.asyncio
async def test_confirmation_keywords_skip_llm(monkeypatch):
    """A confirmation keyword is answered without an LLM call (#217)"""
    # Without a key, LLMClient returns a dummy response and never reaches ChatAnthropic.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    sent = []

    # Count instead of raising: is_rejection's `except Exception` would swallow a raise.
    async def counting_ainvoke(self, messages, *args, **kwargs):
        sent.append(messages)
        return AIMessage(content="NO")

    monkeypatch.setattr(ChatAnthropic, "ainvoke", counting_ainvoke)
    cm = ConversationManager()

    for keyword in ["proceed", "yes", "Go ahead "]:
        assert await cm.is_confirmation(keyword) is True
    assert sent == []


@pytest.mark.asyncio
async def test_conversation_llm_calls_tagged_outside_query_cost(monkeypatch):
    """Remaining LLM calls are traced, but not as portal:exploratory roots (#217)

    Cost telemetry counts every portal:exploratory root run as one query.
    """
    cm = ConversationManager()
    run_tags = []

    async def recording_complete(*args, **kwargs):
        run = get_current_run_tree()
        run_tags.append(run.tags if run else None)
        return "NO"

    monkeypatch.setattr(cm.llm_client, "complete", recording_complete)

    with tracing_context(enabled="local"):
        await cm.is_rejection("yes please")
        await cm.detect_intent("what about men?")

    assert len(run_tags) == 2
    for tags in run_tags:
        assert tags is not None
        assert "conversation-manager" in tags
        assert "portal:exploratory-overhead" in tags
        assert "portal:exploratory" not in tags


@pytest.mark.asyncio
async def test_stats_tracking():
    """Test that stats are tracked correctly"""
    cm = ConversationManager()

    # Make some calls
    await cm.detect_intent("hello")
    await cm.detect_intent("what's the status?")
    await cm.detect_intent("show me patients")

    # Check stats
    stats = cm.get_stats()
    assert stats["total_calls"] == 3
    assert stats["pattern_matches"] + stats["llm_fallbacks"] == 3
    assert stats["llm_percentage"] + stats["pattern_percentage"] == pytest.approx(100, rel=1)


@pytest.mark.asyncio
async def test_edge_cases():
    """Test edge cases"""
    cm = ConversationManager()

    # Empty string
    intent = await cm.detect_intent("")
    assert intent in [UserIntent.UNKNOWN, UserIntent.QUERY]

    # Very long query
    long_query = "how many patients with diabetes and hypertension who had a hospital admission in 2023 and are over 50 years old"
    intent = await cm.detect_intent(long_query)
    assert intent == UserIntent.QUERY

    # Mixed case
    intent = await cm.detect_intent("HOW MANY patients?")
    assert intent == UserIntent.QUERY
