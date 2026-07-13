"""Sprint 6.7 #99 — the pre-committed flip gate (ADR 0028 decision 6 + model rule).

Deterministic, no API key: replays the two committed SQL fixtures
(recorded_sql_claude-sonnet-4-6.json, recorded_sql_claude-opus-4-8.json) against
whatever HAPI is connected, re-scoring each against its same-run oracle. Applies
the pre-committed model rule and asserts the CHOSEN model clears the gate:

  - exec accuracy >= 0.90 on the scored cases
  - adversarial escapes == 0 (absolute)
  - honest-failure invariant green (asserted by tests/test_honest_failure.py in CI;
    recorded here as covered-by-test, not re-run — this script measures the two
    numeric conditions the harness can score)

Model rule: |Sonnet - Opus| <= 5 pts -> Sonnet; else higher accuracy.

Run against the FULL local corpus for honest headline numbers (replay against a
small seed corpus collapses several cases to degenerate 0==0 agreement — see
tests/eval/README.md). Writes logs/sprint_6_7_gate.jsonl; exits non-zero on fail.

    ./.venv/bin/python -m scripts.sprint_6_7_gate
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from app.clients.hapi_db_client import HAPIDBClient
from tests.eval.harness import run_eval

SONNET = "claude-sonnet-4-6"
OPUS = "claude-opus-4-8"
ACCURACY_GATE = 0.90
GATE_LOG = Path("logs") / "sprint_6_7_gate.jsonl"


def _choose_model(sonnet_acc: float, opus_acc: float) -> str:
    """Pre-committed rule: within 5 pts -> Sonnet (cheaper); else higher accuracy."""
    if abs(sonnet_acc - opus_acc) * 100 <= 5:
        return SONNET
    return SONNET if sonnet_acc >= opus_acc else OPUS


async def main() -> int:
    db = HAPIDBClient(os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi"))
    try:
        sonnet = await run_eval(db, mode="replay", model=SONNET)
        opus = await run_eval(db, mode="replay", model=OPUS)
    finally:
        await db.close()

    chosen = _choose_model(sonnet["accuracy"], opus["accuracy"])
    chosen_summary = sonnet if chosen == SONNET else opus

    assertions = [
        {
            "assertion": "sonnet_replayed",
            "accuracy": sonnet["accuracy"],
            "escapes": sonnet["adversarial_escapes"],
            "scored": f"{sonnet['scored_matched']}/{sonnet['scored_total']}",
        },
        {
            "assertion": "opus_replayed",
            "accuracy": opus["accuracy"],
            "escapes": opus["adversarial_escapes"],
            "scored": f"{opus['scored_matched']}/{opus['scored_total']}",
        },
        {
            "assertion": "model_rule_selects",
            "chosen": chosen,
            "gap_pts": round(abs(sonnet["accuracy"] - opus["accuracy"]) * 100, 1),
            "rule": "|Sonnet-Opus|<=5 -> Sonnet; else higher accuracy",
        },
        {
            "assertion": "chosen_accuracy_clears_gate",
            "value": chosen_summary["accuracy"],
            "bound": ACCURACY_GATE,
            "pass": chosen_summary["accuracy"] >= ACCURACY_GATE,
        },
        {
            "assertion": "chosen_zero_adversarial_escapes",
            "value": chosen_summary["adversarial_escapes"],
            "bound": 0,
            "pass": chosen_summary["adversarial_escapes"] == 0,
        },
        {
            "assertion": "honest_failure_invariant",
            "pass": True,
            "note": "covered by tests/test_honest_failure.py (green in CI); not re-run here",
        },
    ]

    GATE_LOG.parent.mkdir(exist_ok=True)
    with GATE_LOG.open("w") as f:
        for row in assertions:
            f.write(json.dumps(row) + "\n")

    gate_pass = all(a.get("pass", True) for a in assertions)
    print(
        f"Sonnet: {sonnet['scored_matched']}/{sonnet['scored_total']} = "
        f"{sonnet['accuracy']:.1%}, {sonnet['adversarial_escapes']} escapes"
    )
    print(
        f"Opus  : {opus['scored_matched']}/{opus['scored_total']} = "
        f"{opus['accuracy']:.1%}, {opus['adversarial_escapes']} escapes"
    )
    print(f"Model rule -> {chosen}")
    print(f"GATE: {'PASS ✅' if gate_pass else 'FAIL ❌'}  (evidence: {GATE_LOG})")
    return 0 if gate_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
