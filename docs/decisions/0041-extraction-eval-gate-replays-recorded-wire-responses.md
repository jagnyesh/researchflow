---
sprint: null
date: 2026-11-18
status: accepted
supersedes: []
superseded_by: null
related: [0040-extraction-eval-scores-concepts-as-the-generator-reads-them.md, 0021-sprint-8-2-prompt-caching-bug.md]
---

# The extraction eval gate replays recorded wire responses in CI (#137)

**Problem.** [ADR 0040](0040-extraction-eval-scores-concepts-as-the-generator-reads-them.md) gave the repo `scripts/run_extraction_evals.py`. The runner measures how often the Formal Portal's Requirements Agent extracts the right [criterion concepts](../../CONTEXT.md). It runs only live, on 12 cases, and nothing gates on it. A change to the extraction prompt, the model, or the code that reads the model's answer can lower extraction accuracy while every check still passes. Running the live eval in CI doesn't fix that. Each run is billed, and extraction runs at temperature 0.3, so one commit can pass on one run and fail on the next.

**Decision (owner, 2026-11-18).**

- **CI replays recorded responses at the Anthropic SDK.** A recording run wraps `anthropic.AsyncMessages.create`, the seam that `TestPromptCachingWireLevel` patches (`tests/test_prompt_optimization.py`). It saves each response's text, stop reason and token usage. A replay run replaces that method and rebuilds each response as an `anthropic.types.Message`. Everything above the SDK runs for real:
  - langchain-anthropic's response parsing;
  - the fence stripping and JSON parse in `LLMClient.extract_structured_json`;
  - the batch's index matching;
  - the agent's retry of a criterion the batch left empty, and its fallback to one call per criterion.
- **A request finds its recording by its content.** The key is a SHA-256 hash of the whole request the SDK receives. That is the model, `max_tokens`, `temperature`, the system prompt and the messages, as read from the wire on 2026-11-18. A change to the sampling settings therefore also needs a new recording. The recording stores the user message as text, so a reviewer can read what was sent, and stores the system prompt as its hash only. Each key holds its responses in call order. One request can occur more than once in a run, and each call can get a different answer.
- **Replay refuses to guess.** The run exits 2, the runner's code for a run that can't be trusted, when:
  - a request has no recording, because a prompt, the model or a criterion changed;
  - a key's recorded responses run out;
  - a recorded response is still unused when the run ends, because the agent's calls no longer match the recording.

  Replay sets a placeholder API key and never reaches HTTP. CI's `test` job sets the real key for its pytest step, and replay must not turn a missing recording into a billed call. As a result, a change to the prompt or the model can't pass CI on an old recording. Someone has to record again, live, and the threshold then applies to the new recording.
- **A re-baseline is five live runs at one commit.** The runner takes `--repeat 5 --record PATH`. Run 1 is the recording, and that is fixed before the runs start, so no one can keep the luckiest of five. The runner prints each run's pass rate, the lowest rate, and the ids of cases that passed in some runs and failed in others. The runner prints a threshold only when every run completed with exit code 0 or 1. Any untrusted run makes the re-baseline exit 2 with no threshold. The recording fails the same way when a call raised during run 1, even if the agent's fallback recovered the case, because the failed request has no response to replay. If run 1 can't be trusted, the runner stops before run 2, so it bills nothing more. The recording is written only after every run is trusted, so a failed re-baseline leaves the committed recording as it was. The recording names its commit with `-dirty` when the tree held uncommitted changes. A change to the case set, the extraction prompt or the model needs a re-baseline. Each live run needs the owner's OK first.
- **The threshold is the lowest pass rate of the five runs, rounded down to one decimal place.** The worst observed run then passes, and so does the recording. The threshold goes up only in a re-baseline PR. Lowering it needs the owner's OK and a line under "Changed expectations" in the PR body.
- **CI runs the gate as a step of the `test` job, on every PR.** The step runs `python -m scripts.run_extraction_evals --replay --fail-under <X> --min-cases <N>`, with an empty API key and tracing off. `test (ubuntu-latest, 3.11)` is already a required check on `main`, so the gate blocks merging from the day it lands. The step runs on every PR, not only on PRs that touch a model-calling path. The scorer, the generator's age and gender parsers, and the agent's retry logic can all move the score.
- **The gate proves it ran.** ADR 0040's runner already exits 2 on a fixture with zero cases and when fewer cases ran than the fixture holds. `--min-cases N` also exits 2 when the fixture holds fewer than N cases. ADR 0040 noted that deleting cases keeps those two counts equal, so the count check alone can't catch it. CI pins N to the size of the case set as merged. The step prints `executed N / expected N`.
- **The evidence log is written whole or not at all** (PR #526 review finding 22). The runner turns every row into JSON before it writes the first one, so a row that can't be serialized writes nothing. If the write itself fails partway, as on a full disk, the runner cuts the log back to its size before the run (review finding 1 on this PR). Either way, no case rows are left without their summary row.
- **An all-error run under `--fail-under` exits 2, and a test pins it** (PR #526 review finding 23). The code already did this, but no test checked it.
- **The case set grows from 12 to 36.** The owner approved 24 new cases on 2026-11-18. They cover:
  - gender, age ranges and age buckets;
  - timing ("in the last 12 months", "before 2020", "before type 2 diabetes diagnosis");
  - negation ("without", "w/o", "no history of", and exclusion lists);
  - several conditions in one criterion, abbreviations and a brand name;
  - four adversarial or ambiguous phrasings: an instruction injected into a criterion, "not over 65", a criterion that names both genders, and familial hypercholesterolemia, which is the patient's own diagnosis.

  Some cases are hard on purpose, so the pass rate has room below 100%. No expected value came from model output.
- **Per-type thresholds wait.** The runner still reports precision and recall for each concept type. With 36 cases, labs and procedures have only a few expected concepts each, so a threshold on either would move on a single case.

**Baseline (2026-11-18).** One owner-approved re-baseline: five live Haiku 4.5 runs, 39 batch calls each, with tracing off. Every run passed 34 of 36 cases (94.4%), and no case flipped between runs. The same two cases failed every time: `in_their_50s_htn` and `both_genders_asthma`, each on a demographic concept. Run 1 is the recording, 39 calls. Its `git_commit` field reads `3f5fd18`, but the runner and the 36 cases that made it were uncommitted changes on that commit; the `-dirty` mark that now flags this came from review. CI therefore runs with `--fail-under 94.4` and `--min-cases 36`. A keyless replay of the recording scores 34 of 36 and exits 0.

**Rejected alternatives.**

- Recording at the agent seam, as `tests/eval/formal_record.py` does. It skips the SDK, so it can't catch drift in how the answer is parsed. [ADR 0021](0021-sprint-8-2-prompt-caching-bug.md) records a bug at that kind of boundary that ran for six months.
- Recording at the HTTP transport. That means reaching into the private client that `ChatAnthropic` builds, which can break on any SDK upgrade.
- A threshold set to the recorded accuracy minus a fixed tolerance. The tolerance would be a guess, not a measure of how much runs vary.
- Three live runs per re-baseline. Three runs miss a case that fails one run in ten 73% of the time; five runs miss it 59% of the time.
- A separate CI job. It would block nothing until the owner added it to the required checks.

**Consequences.**

- CI's score is the recording's score. A green replay means the code still reads the recorded answers the same way. It doesn't mean today's model gives those answers. Only a re-baseline measures the model.
- Any edit to the extraction prompt fails CI until someone records again. The re-baseline is about 39 batch calls per run, plus retries, so about 200 billed calls.
- The recording holds synthetic criteria and the model's answers. It is checked for keys and tokens before each commit.
