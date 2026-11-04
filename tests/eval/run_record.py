"""Sprint 6.7 #98 — record-mode driver: run the live model over the eval cases,
save the synthesized SQL fixtures + a JSONL row per case, print the summary.

Local / #99 gate use (needs ANTHROPIC_API_KEY + running HAPI):

    ANTHROPIC_API_KEY=... \
    ./.venv/bin/python -m tests.eval.run_record --model claude-sonnet-4-6

Writes:
  tests/eval/fixtures/recorded_sql_<model>.json   (replayed by CI)
  logs/eval_<model>.jsonl                          (per-case detail)
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.clients.hapi_db_client import HAPIDBClient
from tests.eval.harness import fixture_path, run_eval, write_jsonl


async def main(model: str) -> None:
    db = HAPIDBClient(os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi"))
    summary = await run_eval(db, mode="record", model=model)
    await db.close()

    # #240: each entry carries its LangSmith-priced cost so replay reports it too.
    fixture = {
        case_id: {"sql": sql, "cost_usd": summary["recorded_cost"].get(case_id)}
        for case_id, sql in summary["recorded_sql"].items()
    }
    fixture_path(model).write_text(json.dumps(fixture, indent=2, sort_keys=True))
    Path("logs").mkdir(exist_ok=True)
    write_jsonl(summary, Path("logs") / f"eval_{model.replace('/', '_')}.jsonl")

    print(f"model            : {summary['model']}")
    print(
        f"scored accuracy  : {summary['scored_matched']}/{summary['scored_total']} = {summary['accuracy']:.1%}"
    )
    print(
        f"full-denominator : {summary['full_denominator_accuracy']:.1%} (unsupported cases count as fails)"
    )
    print(
        f"adversarial      : {summary['adversarial_escapes']} escapes / {summary['adversarial_total']}"
    )
    median, per_pass = summary["median_cost_per_attempt_usd"], summary["cost_per_passing_query_usd"]
    print(f"median cost/try  : {'unknown' if median is None else f'${median:.6f}'}")
    print(f"cost per passing : {'unknown' if per_pass is None else f'${per_pass:.6f}'}")
    priced = sum(1 for c in summary["recorded_cost"].values() if c is not None)
    print(f"priced cases     : {priced}/{len(summary['recorded_cost'])}")
    print("\nper-case:")
    for r in summary["results"]:
        tag = (
            ("✅" if r["matched"] else "❌")
            if r["kind"] == "scored"
            else ("🚨ESCAPE" if r["escaped"] else "🛡️ ok")
        )
        print(f"  {tag:8} {r['id']:32} {r['note'][:70]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-sonnet-4-6")
    args = ap.parse_args()
    asyncio.run(main(args.model))
