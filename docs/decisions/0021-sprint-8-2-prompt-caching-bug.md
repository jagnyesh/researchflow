---
sprint: 8.2
date: 2026-05-14
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 8.2 — The 6-month silent prompt-caching bug: langchain-anthropic transmission gap

### Setup

Sprint 8 (2025, archive doc `docs/sprints/archive/SPRINT_08_PROMPT_OPTIMIZATION.md`) projected a 73% cost reduction primarily from prompt caching. The optimization was implemented in `app/utils/llm_client.py:354-370`:

```python
messages.append(
    SystemMessage(
        content=system,
        additional_kwargs={"cache_control": {"type": "ephemeral"}}
    )
)
```

Sprint 8.1 (2026-05-12) verified the claim against production traffic: median cost-per-request was $0.009026 (formal) vs $0.003 projected (3.01× the band ceiling), `cache_hit_rate = 0.0%` on every observed run. The verdict was RED.

### What Sprint 8.2 found

Three concurrent failure modes, not one:

**(1) Wrong message shape for the transmission layer.** `langchain-anthropic 1.0.1`'s `_format_messages` (`chat_models.py:352-366`) translates a `SystemMessage` to Anthropic's API kwargs by branching on `message.content` type:
- If `content` is a **list of content blocks** (e.g., `[{"type": "text", "text": "...", "cache_control": {...}}]`), the blocks are passed through to Anthropic's API as `system=[...]`, preserving `cache_control`.
- If `content` is a **plain string**, the branch sends `system="..."` to Anthropic. **`additional_kwargs.cache_control` is silently discarded.**

Sprint 8 shipped the string-content + additional_kwargs form. cache_control never reached Anthropic for ~6 months.

**(2) System prompts below Anthropic's minimum cacheable token threshold.** Even if `cache_control` had reached the wire, the system message was `"You are a helpful clinical research data specialist."` (~12 tokens). Anthropic Sonnet 4 silently ignores `cache_control` on prompts below ~1024 tokens; Haiku 4.5 below ~2048 tokens (empirically appears to be even higher). With 12 tokens, no caching would have happened regardless.

**(3) Existing unit tests asserted against the input shape, not the wire shape.** `TestPromptCachingEnabled` checked `assert "cache_control" in system_msg.additional_kwargs` — which langchain-anthropic *receives* but then *discards*. The tests passed for 6 months while the wire-level behavior was broken. Sprint 8.2's diagnostic (Task 1) inspected the LangSmith trace inputs (the same input shape) and concluded "wiring correct" — same mistake.

### Why this matters beyond the immediate fix

This is the failure mode the Sprint 6.2 pivot rule and Sprint 8.1 pre-committed gate were designed to catch. The system *worked* end-to-end — requests succeeded, cost telemetry recorded numbers, dashboards rendered — but the load-bearing optimization was silently disabled by a third-party wrapper translation. No exception, no warning, no test failure. The only signal was `cache_hit_rate = 0.0%` against the expected positive number, and that signal took 6 months to investigate because the verdict's wrong-projection assumption made the cost numbers look explainable.

### Fixes shipped (PR #43)

**(1) Content-block form** — `llm_client.py` always emits SystemMessage with content as a list of content blocks:

```python
SystemMessage(content=[
    {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
])
```

This is the only form `langchain-anthropic` actually transmits to Anthropic's API.

**(2) Substantive system prompts above threshold** — module-level `_REQUIREMENTS_SYSTEM_PROMPT` (~3000 tiktoken tokens, Sonnet) and `_MEDICAL_CONCEPTS_SYSTEM_PROMPT` (~2500 tiktoken tokens, Haiku-target). Byte-stable across calls (no f-string interpolation) — required for cache key stability. User messages become minimal (dynamic content only).

**(3) Wire-level integration test** — `TestPromptCachingWireLevel.test_cache_control_reaches_anthropic_wire_for_custom_system_prompt` mocks `anthropic.resources.messages.AsyncMessages.create` and asserts `cache_control` arrives in the outbound `system` kwarg as a content-block array. Verified to catch the buggy shape (test fails when reverted) AND pass with the fix (test passes when restored). Future maintainers cannot revert the fix without breaking this test.

**(4) Unit test updates** — `TestPromptCachingEnabled` updated to assert content-block form, not `additional_kwargs`. Brings the input-level tests in alignment with the wire-level reality.

### Empirical verification (LangSmith, 2026-05-14)

After the fix, 7 fresh formal-portal requests through `scripts/drive_qa_traffic.py`. Every Sonnet 4.6 `extract_requirements` call now shows `cache_create=3087` on first call (in the 5-min TTL window) and `cache_read=3087` on subsequent calls. Haiku 4.5 `extract_medical_concepts` still shows `cache_create=0` — its threshold appears higher than the 2500-token prompt currently provides; filed as Sprint 8.2 follow-up Task 2.1.

### Implications for the Sprint 8 archive doc projection

The Sprint 8 archive doc's 73% cost-reduction projection assumed cache_control was working as wired. Per the fixes above:
- It wasn't working (root cause #1).
- The system prompts wouldn't have cached anyway (root cause #2).
- The tests wouldn't have caught it (root cause #3).

With root cause #1 + #2 fixed (Sonnet now caches; Haiku pending), the actual achievable reduction is **30-50% per request, not 73%**. Archive doc updated 2026-05-14 with a "Verdict revision" section that names this honestly: the optimization shipped, the dependency stack silently disabled it, the silent disablement is now found and fixed.

### Why the test was the most important addition

The 6-month silent bug existed BECAUSE the existing tests asserted at the wrong layer. Input-shape assertions (LangChain message construction) passed while wire-shape behavior (what Anthropic actually receives) was broken. Adding the wire-level test brings the test surface in alignment with what we actually need to verify — and prevents the same class of regression from running 6 months again on a future LangChain version bump.

This is the structural lesson: **for fixes whose correctness depends on third-party library behavior, the test must assert the third-party API contract, not the wrapper API contract.** The wrapper is the system under test only for unit tests; the wire is the system under test for integration tests. We had the unit tests; we lacked the integration tests.
