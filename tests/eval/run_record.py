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

    fixture_path(model).write_text(json.dumps(summary["recorded_sql"], indent=2, sort_keys=True))
    Path("logs").mkdir(exist_ok=True)
    write_jsonl(summary, Path("logs") / f"eval_{model.replace('/', '_')}.jsonl")

    print(f"model            : {summary['model']}")
    print(
        f"scored accuracy  : {summary['scored_matched']}/{summary['scored_total']} = {summary['accuracy']:.1%}"
    )
    print(
        f"adversarial      : {summary['adversarial_escapes']} escapes / {summary['adversarial_total']}"
    )
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
