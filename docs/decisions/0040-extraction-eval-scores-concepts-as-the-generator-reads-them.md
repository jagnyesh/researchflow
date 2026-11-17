---
sprint: null
date: 2026-11-16
status: accepted
supersedes: []
superseded_by: null
related: [0036-formal-criteria-build-or-fail.md, 0039-formal-family-history-gender-two-bound-age.md, 0028-sprint-6-7-exploratory-llm-sql-synthesis.md]
---

# The extraction eval scores concepts the way the SQL generator reads them (#136)

**Problem.** The Formal Portal's Requirements Agent turns each submitted criterion into [criterion concepts](../../CONTEXT.md) with one Haiku call per criteria list (`RequirementsAgent._criteria_to_structured`, `app/agents/requirements_agent.py`). Nothing measures how often that extraction is right. The formal gold set (`tests/eval/formal_cases.py`, #239) scores the agent and `SQLGenerator` together through the SQL, so it can't say which of the two got a case wrong. #137 (a CI regression gate) and #142 (predicate-survival cases) both need an extraction-only measurement first.

A concept is `{term, type, details}`. Negation, age bounds, gender, and timing live in the free-text `details`. The criterion's `codes` field is hardcoded to `[]`, and nothing reads it. `SQLGenerator` (`app/utils/sql_generator.py`) is the only consumer of `details`, and it already reads them with deterministic parsers.

**Decision (owner, 2026-11-16).**

- **A concept is scored as the generator reads it.** The harness turns each concept into a canonical tuple with the generator's own parsers, so a second parser can't drift from the one that builds the SQL:
  - condition, medication, procedure, or lab: `(type, term, polarity)`. The polarity checks run in the generator's order, and the first match wins:
    1. `excluded`, when the details of a concept in an inclusion list hold the word `excluded`;
    2. `drug_class`, when a medication's details say `drug class`;
    3. `family_history`, when `SQLGenerator._FAMILY_HISTORY` matches a condition's term and details;
    4. `has` otherwise.

    The generator fails a drug-class medication in either list, so no fixture polarity matches `drug_class` (owner, 2026-11-16, from review finding 5). In an inclusion list a medication marked both `drug class` and `excluded` scores `excluded`, because the generator also checks that marker first. With `excluded` first, "family history, excluded" doesn't pass as a family history (owner, 2026-11-16, from review finding 12). Like the generator, the scorer reads no other negation word in a record concept's details, so "no family history" still scores as `family_history`.
  - demographic: `("age", op, value)` from `SQLGenerator._parse_age_details`, or `("gender", "=", value)` from the generator's gender rule. A detail the generator can't build is its own tuple, so it never matches an expectation. That includes an age or gender marked `excluded` in an inclusion list, and non-empty details that aren't a string, which the generator fails on (owner, 2026-11-16, from review finding 13). Empty details of any type read as no details, as they do in the generator.
  - `demographics` (plural) counts as `demographic`, as it does in the generator.
- **A term matches an accepted-term list.** The fixture lists the terms the owner accepts for each expected concept. A term matches when it equals one of them after lowercasing and collapsing whitespace. Substring matching is not used, because the generator's `LIKE '%term%'` makes "type 2 diabetes" and "diabetes" pick different cohorts.
- **In an exclusion list, `excluded` and `has` are the same polarity.** The list already negates the concept ([ADR 0036](0036-formal-criteria-build-or-fail.md)).
- **Some fields are not scored:**
  - `codes`, until a terminology step fills it (#154);
  - lab value thresholds, which no consumer reads today;
  - temporal qualifiers, which the runner reports for each case but which don't affect pass or fail until a consumer reads them. No generator parser exists for them, so the harness has a small one of its own for `within the last N days, weeks, months, or years`.
- **A case passes only on an exact match.** Every expected concept must be present, with no extra concepts, for every criterion in both lists. The runner also reports concept-level precision and recall for each concept type, so #137 can set thresholds for each domain. Matching takes the first returned concept that fits each expectation in order, not the best assignment. Two expectations whose accepted terms overlap could then pass or fail depending on the order of the returned concepts. No seed case has such an overlap.
- **A case is one form submission.** It holds an inclusion list and an optional exclusion list of criterion strings, with expected concepts for each criterion. The runner calls `RequirementsAgent()._criteria_to_structured` once for each non-empty list. That call is the live path: one batch call, a single retry for each criterion the batch left empty, and a fallback to one call per criterion if the batch fails. A raised error fails the case and records only the error's class, never the criterion text or the model's raw output. Every concept the errored case expected counts as a miss in its type's recall.
- **The case set is a golden file.** It lives in `tests/eval/fixtures/extraction_cases.json`, a path that `docs/DAILY_DEV_WORKFLOW.md` §7 names as a golden file. The lock is a rule today. The §7 CI diff check that would enforce it isn't built. A top-level `format` object documents the fields, because JSON has no comments. Every case carries a `signoff`, and the loader rejects the file if one is missing. The loader also rejects unknown keys, because a misspelled `exclusion` would leave its criteria unsent and unscored. It rejects any expected age that `_parse_age_details` never returns, because a case built on one could never pass. The owner approved all 12 seed cases and their expected values on 2026-11-16. No expected value came from model output.
- **The runner proves that it ran.** `scripts/run_extraction_evals.py` exits:
  - `0` when the run is complete;
  - `1` when accuracy is below `--fail-under`, which is off by default;
  - `2` when the run can't be trusted: the fixture has zero cases, the number of cases executed differs from the number in the fixture, the fixture fails to load or lacks a signoff, no live LLM client exists, every case errored, the evidence log can't be written, or the run raised an error nothing else handled. Python's own exit code for that last case is 1, which would read as below threshold. `--fail-under` takes only a percentage from 0 to 100.

  The no-client refusal matters because `LLMClient.complete` returns a canned response when no API key is set (`app/utils/llm_client.py`). Without the refusal, a keyless run would score canned output and look like a measurement. A run in which every case errored is refused for the same reason: an expired key or an outage would otherwise read as a 0% extractor (owner, 2026-11-16, from review finding 4). A run with some errors stays scored, and its errors count as failures. Exit `2` wins over exit `1`.
- **The evidence goes to `logs/extraction_evals.jsonl`.** That path is gitignored. Each row holds the timestamp, case id, list, criterion, expected concepts, the concepts returned, their canonical tuples, the pass result, the error class if any, and the git commit. The returned concepts let a later scoring rule re-score a run, because a canonical tuple can hide a detail, such as an age marked `excluded`. The summary row also holds the run's exit code and its integrity failure, if any, so a reader such as #137 can drop a run that measured nothing (owner, 2026-11-16, from review finding 15). Criteria are synthetic phrasings, so logging them is safe.
- **The baseline is one live run.** Extraction runs at temperature 0.3, so one run is one sample, and a case can flip between runs. #137 decides how many repeats a gate needs. Each live run is billed and needs the owner's OK first. Every other run, the tests included, is keyless.

**Rejected alternatives.**

- An LLM judge. It isn't deterministic, so #137 couldn't use it as a CI gate (#75's flaky-test lesson).
- A harness-owned parser for all of `details`. It would be independent of the generator, but it could disagree with the parser that builds the SQL. The eval would then score a meaning that no cohort gets.
- Changing extraction to emit structured predicates. That changes production behavior and belongs to its own issue.
- Calling `LLMClient.extract_medical_concepts_batch` directly. It skips the agent's retry and fallback, so it would measure less than the portal runs.
- Scoring a keyless run as all-fail. The result would look like a measurement, which is the failure §5 warns about.

**Consequences.**

- A change to the generator's parsers can change an extraction score with no change to extraction. That is intended: the eval measures whether the generator gets the concept it needs.
- The tests use a fake `extract` function at the agent seam, never a mocked SDK or HTTP client. They can't catch drift at the wire. The live run is the only wire-level evidence.
- Deleting cases keeps the counts equal, so the count check can't catch it. The golden-file lock (§7) and the always-human merge for High-tier changes catch it.
