"""Drive synthetic traffic through both portals for Sprint 8.1 cost-telemetry gate.

Calls LangGraphRequestFacade.process_new_request (formal) and
QueryInterpreter/FeasibilityService directly (exploratory). No browser —
the @traceable decorators sit on the same call path, so LangSmith traces
are identical to manually driving through Streamlit.

Usage:
    uv run python scripts/drive_qa_traffic.py                   # both portals, n=30 each
    uv run python scripts/drive_qa_traffic.py --portal formal   # formal only
    uv run python scripts/drive_qa_traffic.py --n 10 --start 5  # 10 starting at case 5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.WARNING, format="%(message)s")
for noisy in ("httpx", "httpcore", "langsmith", "langchain", "asyncio", "sqlalchemy.engine"):
    logging.getLogger(noisy).setLevel(logging.ERROR)


RESEARCHER = {
    "name": "Auto Driver",
    "email": "auto-driver@test.edu",
    "department": "Informatics",
    "irb_number": "IRB-AUTO-2026",
}

DIAGNOSES = [
    ("diabetes", "diabetes mellitus"),
    ("hypertension", "essential hypertension"),
    ("CHF", "congestive heart failure"),
    ("asthma", "asthma"),
    ("COPD", "chronic obstructive pulmonary disease"),
    ("AFib", "atrial fibrillation"),
]

# 5 demographic buckets per diagnosis × 6 diagnoses = 30 unique cases
DEMO_BUCKETS = [
    ("male", "18-40", 18, 40),
    ("female", "18-40", 18, 40),
    ("male", "40-65", 40, 65),
    ("female", "40-65", 40, 65),
    ("any", "65+", 65, None),
]

CASES = [(dx, demo) for dx in DIAGNOSES for demo in DEMO_BUCKETS]
assert len(CASES) == 30, f"expected 30 unique cases, got {len(CASES)}"

EXPLORATORY_PHRASINGS = [
    "How many {gender} patients with {dx} between ages {amin}-{amax_or_plus}?",
    "Count {gender} patients diagnosed with {dx}, age {amin}-{amax_or_plus}",
    "Find all {gender} patients aged {amin}-{amax_or_plus} who have {dx}",
    "Patients with {dx} — {gender}, age {amin} to {amax_or_plus}",
    "Show me {dx} cases in {gender} patients ages {amin}-{amax_or_plus}",
]


def _gender_word(g: str) -> str:
    return "" if g == "any" else g


def _age_phrase(amin: int, amax: int | None) -> tuple[str, str]:
    if amax is None:
        return f"age {amin}+", f"{amin}+"
    return f"age {amin}-{amax}", f"{amax}"


def make_formal_payload(idx: int) -> tuple[str, dict]:
    (dx_short, dx_long), (gender, _, amin, amax) = CASES[idx]
    g_word = _gender_word(gender) or "all"
    age_phrase, _ = _age_phrase(amin, amax)
    request_text = (
        f"I need clinical data and demographics for {g_word} patients with "
        f"{dx_long} ({age_phrase}). Sprint 8.1 cost-telemetry seed run {idx + 1}/30."
    )
    inclusion = [f"Age >= {amin}"]
    if amax is not None:
        inclusion.append(f"Age <= {amax}")
    if gender != "any":
        inclusion.append(f"Gender: {gender}")
    inclusion.append(f"Diagnosis: {dx_long}")
    structured = {
        "inclusion_criteria": inclusion,
        "exclusion_criteria": [],
        "data_elements": ["Demographics (age, gender, race)"],
        "time_period": {"start": None, "end": None},
        "phi_level": "de-identified",
    }
    researcher_info = {**RESEARCHER, "structured_requirements": structured}
    return request_text, researcher_info


def make_exploratory_query(idx: int) -> str:
    (dx_short, dx_long), (gender, _, amin, amax) = CASES[idx]
    template = EXPLORATORY_PHRASINGS[idx % len(EXPLORATORY_PHRASINGS)]
    g_word = _gender_word(gender) or "all"
    _, amax_phrase = _age_phrase(amin, amax)
    return template.format(
        gender=g_word.strip() or "any", dx=dx_long, amin=amin, amax_or_plus=amax_phrase
    )


async def drive_formal(start: int, n: int) -> list[dict]:
    from app.langchain_orchestrator.request_facade import LangGraphRequestFacade

    facade = LangGraphRequestFacade(use_real_agents=True, use_persistence=True)
    out: list[dict] = []
    for i in range(start, start + n):
        case_idx = i % len(CASES)
        (dx_short, _), (gender, age_label, _, _) = CASES[case_idx]
        request_text, researcher_info = make_formal_payload(case_idx)
        t0 = time.monotonic()
        try:
            request_id = await facade.process_new_request(
                researcher_request=request_text,
                researcher_info=researcher_info,
                from_formal_portal=True,
            )
            elapsed = time.monotonic() - t0
            print(
                f"  [F {i + 1:02d}/{start + n}] {dx_short:12s} {gender:6s} {age_label:5s} "
                f"→ {request_id}  ({elapsed:.1f}s)"
            )
            out.append({"idx": i, "request_id": request_id, "elapsed": elapsed})
        except Exception as e:
            elapsed = time.monotonic() - t0
            print(
                f"  [F {i + 1:02d}/{start + n}] {dx_short:12s} {gender:6s} {age_label:5s} "
                f"ERROR after {elapsed:.1f}s: {type(e).__name__}: {e}"
            )
            out.append({"idx": i, "request_id": None, "error": str(e)})
    return out


async def drive_exploratory(start: int, n: int) -> list[dict]:
    from app.services.feasibility_service import FeasibilityService
    from app.services.query_interpreter import QueryInterpreter

    qi = QueryInterpreter()
    fs = FeasibilityService()
    out: list[dict] = []
    for i in range(start, start + n):
        query = make_exploratory_query(i)
        t0 = time.monotonic()
        try:
            intent = await qi.interpret_query(query)
            intent_dict = intent.__dict__ if hasattr(intent, "__dict__") else intent
            data = await fs.execute_feasibility_check(intent_dict)
            # Match research_notebook.py pattern: close+recreate per call
            try:
                await fs.close()
            except Exception:
                pass
            fs = FeasibilityService()
            elapsed = time.monotonic() - t0
            est = data.get("estimated_cohort", "?")
            (dx_short, _), (gender, age_label, _, _) = CASES[i % len(CASES)]
            print(
                f"  [E {i + 1:02d}/{start + n}] {dx_short:12s} {gender:6s} {age_label:5s} "
                f"cohort~{est:>4}  ({elapsed:.1f}s)"
            )
            out.append({"idx": i, "cohort": est, "elapsed": elapsed})
        except Exception as e:
            elapsed = time.monotonic() - t0
            print(
                f"  [E {i + 1:02d}/{start + n}] ERROR after {elapsed:.1f}s: "
                f"{type(e).__name__}: {e}"
            )
            out.append({"idx": i, "cohort": None, "error": str(e)})
    try:
        await fs.close()
    except Exception:
        pass
    return out


async def print_telemetry(label: str) -> None:
    try:
        from app.services.cost_telemetry_service import CostTelemetryService

        svc = CostTelemetryService()
        f = await svc.get_formal_portal_cost_p50(n=30)
        e = await svc.get_exploratory_portal_cost_p50(n=30)
        print(f"\n=== Cost telemetry {label} ===")
        print(
            f"  Formal       n={f.n_observed:>2}/30  median=${f.median_usd:.6f}  "
            f"band ≤ ${f.band_ceiling_usd}  gate={f.gate_status}"
        )
        print(
            f"  Exploratory  n={e.n_observed:>2}/30  median=${e.median_usd:.6f}  "
            f"band ≤ ${e.band_ceiling_usd}  gate={e.gate_status}\n"
        )
    except Exception as ex:
        print(f"\n  telemetry read failed: {type(ex).__name__}: {ex}\n")


async def main(args: argparse.Namespace) -> None:
    os.environ.setdefault("LANGCHAIN_PROJECT", "researchflow-production")
    await print_telemetry("(before)")

    if args.portal in ("formal", "both"):
        print(f"--- Driving FORMAL portal ({args.n} requests, start={args.start}) ---")
        t0 = time.monotonic()
        await drive_formal(args.start, args.n)
        print(f"  formal batch took {time.monotonic() - t0:.1f}s")

    if args.portal in ("exploratory", "both"):
        print(f"\n--- Driving EXPLORATORY portal ({args.n} queries, start={args.start}) ---")
        t0 = time.monotonic()
        await drive_exploratory(args.start, args.n)
        print(f"  exploratory batch took {time.monotonic() - t0:.1f}s")

    await print_telemetry("(after)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--portal", choices=("formal", "exploratory", "both"), default="both")
    p.add_argument("--n", type=int, default=30, help="requests per portal")
    p.add_argument("--start", type=int, default=0, help="case index to start from (0-29)")
    args = p.parse_args()
    asyncio.run(main(args))
