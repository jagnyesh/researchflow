---
status: in-progress
supersedes: []
superseded_by: null
related: []
---

# Meta: Recurring workflow pattern — re-examining recommendations when premise may have shifted

Across roughly 48 hours of intense sprint work (2026-05-12 through 2026-05-15),
I encountered the same recurring failure mode roughly 10 times. The shape is
identical each time: an AI agent applies a framework correctly given visible
information; the visible information has a load-bearing assumption that hasn't
been pressure-tested; deliberate re-examination surfaces a richer truth than
the original framing could accommodate; the right action involves updating the
rule, not mechanically applying it.

### The cases

1. **Sprint 8.2 Task 1 (cache diagnostic):** Binary YES/NO frame on cache_control
   wiring → third branch (wired correctly, but system prompt below Anthropic
   threshold).

2. **Sprint 6.3 D4 candidate search:** "DuckDB-FHIR candidates exist as described"
   → didn't exist as named; sqlonfhir surfaced through user-initiated re-search.

3. **Sprint 6.3 verdict revision:** Literal pre-commit said NO-GO for sqlonfhir →
   gate premise was broken by view-def bug #41; fixing #41 changed evidence;
   verdict revised via Q1-refinement override.

4. **Sprint 6.3 post-spike /zoom-out:** Routine architectural verification →
   documented architecture (HybridRunner read path) vs runtime reality (agents
   bypass Runner stack). Five architectural gaps surfaced.

5. **Sprint 8.2 Task 2 (prompt architecture):** "Fix prompt architecture so
   caching engages" → langchain-anthropic 1.0.1 silent transmission bug, dropping
   cache_control for 6 months. The wrapper bug was the real issue, not prompt size.

6. **Sprint 8.2 Task 3 (re-measurement):** "Verify optimization works post-Sonnet
   caching" → bulk-up cost offsets cache savings; original 73% projection was
   wrong by 2-3× because cost model assumed 6 LLM calls per request when actual
   is ~2.

7. **Sprint 8.2 Task 2.1 (prompt bulk-up):** "Respect pre-committed 4200-4500
   token band" → 5185 tokens; band was a guideline, not a constraint; deliberate
   proceed-as-is was right rather than mechanical trim-to-fit.

8. **Sprint 8.4 aggregator bug:** Static-analysis hypothesis (parent+child run
   summation double-count) → wire-level empirical check revealed input_tokens
   already includes cache_read; single-leaf double-charging, not summation.

9. **Sprint 8.3 ceiling derivation:** "1.3× tolerance on measured median" →
   mathematically identical to Sprint 8.1's formula but semantically different
   (cost target vs regression alarm). Math hides semantic shift; honest framing
   preserves distinction.

10. **Post-Sprint-8 /zoom-out:** Routine architectural verification → phenotype
    SQL drops gender/age predicates in some cases (Gap #6). A correctness bug
    nobody was asking about, surfaced by structural investigation.

### The pattern

Agents are good at applying rules to visible information. They're less good at
recognizing when the rule's premise has shifted. The defense is asking, before
accepting a recommendation: "what would have to be true for this verdict to be
wrong?" Usually 30-45 minutes of targeted re-examination either confirms the
verdict with stronger evidence or surfaces a third branch the original frame missed.

The trigger I learned to look for: when an agent's recommendation comes back,
read the cons/concerns section twice as carefully as the pros. The load-bearing
hand-waved assumption usually lives in the cons.

### The defense

Pre-commitments defend against bias, not against information. Better information
justifies deliberate override when documented. Precedent: Sprint 6.2 Phase 1.5
Q1 refinement — pre-committed pivot rule was deliberately refined when new
information ("cataloged mechanical bugs are Phase 1.2 scope, not pivot triggers")
surfaced before the gate fired.

### The cost-benefit

~30-45 min per spike or major decision. Across the 10 cases above, ~3 hours of
re-examination work surfaced: 3 silent bugs (Task 1 prompt size, langchain
transmission, aggregator double-charge), 1 architecture drift (Runner stack
bypass), 1 correctness bug (phenotype SQL predicate-dropping), 1 reversed verdict
(Sprint 6.3 GO sqlonfhir not GO Pathling), and multiple framing improvements.
Asymmetric ROI.

### The transferable observation

This pattern likely generalizes beyond this project. Any AI-augmented engineering
work in stacks with multiple interfa[...truncated; finish this section when polishing the note]
