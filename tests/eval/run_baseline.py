"""Sprint 6.7 #98 — baseline: score the LEGACY path (QueryInterpreter +
JoinQueryBuilder, USE_LLM_SQL_SYNTHESIS off) on the same scored cases, so the
new path's accuracy has a documented number to beat. Expected: age-criteria
cases miss (the #76 dropped-predicate bug) among others.

    ./.venv/bin/python -m tests.eval.run_baseline

Writes logs/eval_baseline.jsonl and prints the accuracy.
"""

import asyncio
import json
import os
from pathlib import Path

from app.clients.hapi_db_client import HAPIDBClient
from app.services.feasibility_service import FeasibilityService
from app.services.query_interpreter import QueryInterpreter
from tests.eval.cases import scored_cases


async def main() -> None:
    os.environ["USE_LLM_SQL_SYNTHESIS"] = "false"  # legacy path
    db = HAPIDBClient(os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi"))
    interpreter = QueryInterpreter()

    rows = []
    matched = 0
    for case in scored_cases():
        note = ""
        got = None
        try:
            intent = await interpreter.interpret_query(case.nl)
            fs = FeasibilityService()
            result = await fs.execute_feasibility_check(
                intent.__dict__ if hasattr(intent, "__dict__") else intent
            )
            await fs.close()
            got = result.get("estimated_cohort")
            oracle_rows = await db.execute_query(case.oracle_sql)
            want = int(list(oracle_rows[0].values())[0])
            ok = got == want
            note = f"got={got} want={want}"
        except Exception as e:
            ok = False
            note = f"error ({type(e).__name__})"
            want = None
        if ok:
            matched += 1
        rows.append({"id": case.id, "category": case.category, "matched": ok, "note": note})
        print(f"  {'✅' if ok else '❌'} {case.id:32} {note[:60]}")

    Path("logs").mkdir(exist_ok=True)
    with (Path("logs") / "eval_baseline.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    n = len(rows)
    print(f"\nLEGACY baseline accuracy: {matched}/{n} = {matched / n:.1%}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
