"""Print gate telemetry (#144): per-gate decisions, reviewer time, what rejections caught.

Read-only over the app database's approvals table; aggregates only, never note
text. Usage: python scripts/gate_telemetry_report.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

if __name__ == "__main__":
    load_dotenv()  # same DATABASE_URL as the app

from app.services.gate_telemetry import CATEGORIES, load_gate_telemetry  # noqa: E402


def render(summary: dict) -> str:
    lines = []
    for gate, s in summary.items():
        c, t = s["counts"], s["reviewer_minutes"]
        rate = "n/a" if s["rejection_rate"] is None else f"{s['rejection_rate']:.0%}"
        median = "n/a" if t["median"] is None else f"{t['median']:.1f}m"
        lines.append(
            f"{gate:<14} approved {c['approved']:>4}  rejected {c['rejected']:>4}  "
            f"modified {c['modified']:>4}  pending {c['pending']:>4}  rejection rate {rate}"
        )
        lines.append(
            f"{'':<14} reviewer time median {median} (n={t['n']}, "
            f"{t['decided_without_timestamp']} decided without reviewed_at)"
        )
        caught = ", ".join(f"{k} {v}" for k, v in s["categories"].items() if v)
        lines.append(f"{'':<14} caught: {caught or 'nothing rejected or modified'}")
    return "\n".join(lines) if lines else "no approvals recorded"


async def main() -> None:
    print(f"Categories: {', '.join(CATEGORIES)}")
    print(render(await load_gate_telemetry()))


if __name__ == "__main__":
    asyncio.run(main())
