"""#239: record the formal gold set live.

    python -m tests.eval.run_formal_record

Sends each approved case's request through the live Requirements Agent
(billed calls; needs ANTHROPIC_API_KEY and running HAPI), writes
tests/eval/fixtures/recorded_requirements_formal.json, scores it, and writes
logs/formal_gold_set.jsonl. CI then replays the fixture (test_formal_replay.py).
"""

import asyncio
from pathlib import Path

from tests.eval.formal_record import record, summary

EVIDENCE = Path("logs/formal_gold_set.jsonl")


def main() -> None:
    scores = asyncio.run(record(EVIDENCE))
    print(summary(scores))
    print(f"Evidence: {EVIDENCE}")


if __name__ == "__main__":
    main()
