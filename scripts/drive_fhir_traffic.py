#!/usr/bin/env python3
"""Synthetic FHIR resource writer for Sprint 6.5's speed-layer architecture.

Without this script, the speed layer has nothing to capture from a Synthea-
seeded HAPI because Synthea data is static. Every write to HAPI bumps
`hfj_resource.res_updated`, which the FHIRSubscriptionService polling loop
(app/services/fhir_subscription_service.py:132) picks up within 30s and
mirrors into Redis. So this writer is the upstream half of every speed-
layer demonstration: it's how new patients flow into the system at
runtime.

Two modes:

- One-shot (default): POST --count patients and exit. Tests use this for
  deterministic "add 1 patient, assert metric row was written" coverage.

- --daemon: POST one patient every --interval seconds until SIGTERM.
  Writes its PID to .streamlit/drive_fhir_traffic.pid so the Phase 3 admin
  dashboard's status indicator can show "running/stopped" without managing
  the subprocess lifecycle from inside Streamlit.

Cohort presets are intentionally clinically nonsensical — fixed
demographics, fixed encounter, fixed observation values. Audience is
data-platform / agentic-AI hires evaluating the *architecture*, not
clinical informaticians evaluating the data quality. Generated patients
can be wildly implausible (1980-01-01 males with diabetes, identical
birthdates for every patient). Doesn't matter. The portfolio claim is
"three-way differential freshness routing works against a live FHIR
write stream," not "the synthetic data is medically defensible."

Usage:
    python scripts/drive_fhir_traffic.py --cohort=t2dm --count=5
    python scripts/drive_fhir_traffic.py --cohort=hypertension --daemon --interval=30
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


FHIR_SERVER = os.getenv("FHIR_SERVER", "http://localhost:8081/fhir")
PID_FILE = Path(__file__).parent.parent / ".streamlit" / "drive_fhir_traffic.pid"


# Cohort presets: SNOMED code + display + matching observation profile.
# Two presets cover the demo + gate use cases; extend here if a third
# cohort (e.g., chronic kidney disease) becomes useful.
COHORT_PRESETS: dict[str, dict] = {
    "t2dm": {
        "condition_system": "http://snomed.info/sct",
        "condition_code": "44054006",
        "condition_display": "Diabetes mellitus type 2 (disorder)",
        # Fasting glucose; elevated value to match a T2DM clinical phenotype
        "observation_system": "http://loinc.org",
        "observation_code": "1558-6",
        "observation_display": "Fasting glucose [Mass/volume] in Serum or Plasma",
        "observation_value": 145.0,
        "observation_unit": "mg/dL",
    },
    "hypertension": {
        "condition_system": "http://snomed.info/sct",
        "condition_code": "38341003",
        "condition_display": "Hypertensive disorder, systemic arterial (disorder)",
        # Systolic BP; elevated value to match hypertension phenotype
        "observation_system": "http://loinc.org",
        "observation_code": "8480-6",
        "observation_display": "Systolic blood pressure",
        "observation_value": 152.0,
        "observation_unit": "mm[Hg]",
    },
}


def build_synthetic_bundle(cohort: str) -> dict:
    """Build a transaction Bundle with Patient + Condition + Observation.

    The Bundle uses urn:uuid: fullUrl references so HAPI assigns canonical
    server-side ids on POST. Resources are minimally compliant FHIR R4 —
    just enough fields to (a) pass HAPI validation and (b) match the SQL
    filters the demo cohort queries use (gender, birth_date, SNOMED code).
    """
    preset = COHORT_PRESETS[cohort]
    patient_urn = f"urn:uuid:{uuid.uuid4()}"
    condition_urn = f"urn:uuid:{uuid.uuid4()}"
    observation_urn = f"urn:uuid:{uuid.uuid4()}"
    now_iso = datetime.now(timezone.utc).isoformat()

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "fullUrl": patient_urn,
                "resource": {
                    "resourceType": "Patient",
                    "gender": "male",
                    "birthDate": "1980-01-01",
                    "name": [{"family": "Synthetic", "given": ["FHIR-Traffic"]}],
                },
                "request": {"method": "POST", "url": "Patient"},
            },
            {
                "fullUrl": condition_urn,
                "resource": {
                    "resourceType": "Condition",
                    "subject": {"reference": patient_urn},
                    "code": {
                        "coding": [
                            {
                                "system": preset["condition_system"],
                                "code": preset["condition_code"],
                                "display": preset["condition_display"],
                            }
                        ],
                        "text": preset["condition_display"],
                    },
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                "code": "active",
                            }
                        ]
                    },
                    "recordedDate": now_iso,
                },
                "request": {"method": "POST", "url": "Condition"},
            },
            {
                "fullUrl": observation_urn,
                "resource": {
                    "resourceType": "Observation",
                    "status": "final",
                    "subject": {"reference": patient_urn},
                    "code": {
                        "coding": [
                            {
                                "system": preset["observation_system"],
                                "code": preset["observation_code"],
                                "display": preset["observation_display"],
                            }
                        ]
                    },
                    "valueQuantity": {
                        "value": preset["observation_value"],
                        "unit": preset["observation_unit"],
                        "system": "http://unitsofmeasure.org",
                        "code": preset["observation_unit"],
                    },
                    "effectiveDateTime": now_iso,
                },
                "request": {"method": "POST", "url": "Observation"},
            },
        ],
    }


async def post_bundle(client: httpx.AsyncClient, bundle: dict) -> tuple[str, str, str]:
    """POST a transaction Bundle and return the (patient_id, condition_id, observation_id)
    assigned by HAPI.

    Raises on non-2xx response so test fixtures get a deterministic failure
    rather than a silently-skipped write.
    """
    response = await client.post(FHIR_SERVER, json=bundle, timeout=30.0)
    response.raise_for_status()
    result = response.json()

    ids = {"Patient": "", "Condition": "", "Observation": ""}
    for entry in result.get("entry", []):
        location = entry.get("response", {}).get("location", "")
        # location looks like "Patient/123/_history/1" — extract resourceType + id
        if "/" in location:
            parts = location.split("/")
            if len(parts) >= 2 and parts[0] in ids:
                ids[parts[0]] = parts[1]

    return ids["Patient"], ids["Condition"], ids["Observation"]


async def write_one(cohort: str) -> tuple[str, str, str]:
    """Build + POST one synthetic patient bundle. Returns the assigned ids.

    Convenience helper for pytest fixtures and the gate script. Creates its
    own httpx client per call — fine for one-shot use, the --daemon loop
    reuses a single client across iterations for connection pooling.
    """
    async with httpx.AsyncClient() as client:
        bundle = build_synthetic_bundle(cohort)
        return await post_bundle(client, bundle)


async def run_one_shot(cohort: str, count: int) -> list[tuple[str, str, str]]:
    """POST `count` synthetic patients and return all assigned id triples."""
    results: list[tuple[str, str, str]] = []
    async with httpx.AsyncClient() as client:
        for i in range(count):
            bundle = build_synthetic_bundle(cohort)
            ids = await post_bundle(client, bundle)
            results.append(ids)
            logger.info(
                f"  [{i + 1}/{count}] POST'd Patient/{ids[0]} + Condition/{ids[1]} "
                f"+ Observation/{ids[2]} (cohort={cohort})"
            )
    logger.info(f"✅ Wrote {count} {cohort} patient(s) to {FHIR_SERVER}")
    return results


async def run_daemon(cohort: str, interval: int) -> None:
    """Loop: POST one patient every `interval` seconds until SIGTERM.

    Writes its PID to PID_FILE for the dashboard's status indicator; cleans
    up the file on shutdown. Catches SIGINT (Ctrl-C) and SIGTERM (e.g.
    `kill` from a terminal) so the file gets removed in both cases.
    """
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    logger.info(f"📌 Daemon started (PID={os.getpid()}, cohort={cohort}, interval={interval}s)")
    logger.info(f"   PID file: {PID_FILE}")
    logger.info(f"   Server:   {FHIR_SERVER}")
    logger.info(f"   Stop:     send SIGTERM (e.g. kill $(cat {PID_FILE}))")

    stop_event = asyncio.Event()

    def _handle_shutdown(signum: int, _frame) -> None:
        signal_name = signal.Signals(signum).name
        logger.info(f"📥 Received {signal_name}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    try:
        async with httpx.AsyncClient() as client:
            count = 0
            while not stop_event.is_set():
                try:
                    bundle = build_synthetic_bundle(cohort)
                    ids = await post_bundle(client, bundle)
                    count += 1
                    logger.info(
                        f"  [{count}] POST'd Patient/{ids[0]} + Condition/{ids[1]} "
                        f"+ Observation/{ids[2]}"
                    )
                except Exception as e:
                    # Don't crash the daemon on a single POST failure — log
                    # and continue. The whole point of --daemon is sustained
                    # write traffic; a transient HAPI hiccup shouldn't kill it.
                    logger.warning(f"  ⚠ POST failed: {e}. Continuing.")

                # Sleep with event check so SIGTERM is responsive even
                # during long intervals.
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
    finally:
        # Cleanup PID file. Wrap in try/except in case the file vanished
        # (e.g., a second daemon instance reaped it) — shutdown should
        # never raise.
        try:
            PID_FILE.unlink()
            logger.info(f"🧹 Removed PID file {PID_FILE}")
        except FileNotFoundError:
            pass
        logger.info(f"✅ Daemon stopped. Wrote {count} patient(s) over the run.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Synthetic FHIR writer for Sprint 6.5 speed-layer demonstrations. "
            "POSTs Patient+Condition+Observation Bundles to HAPI; bumped "
            "res_updated triggers FHIRSubscriptionService → Redis within 30s."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cohort",
        required=True,
        choices=sorted(COHORT_PRESETS.keys()),
        help="Cohort preset (SNOMED code + observation profile)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="One-shot mode: number of patients to POST (default 1). Ignored in --daemon.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Daemon mode: seconds between POSTs (default 10)",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as daemon: POST every --interval seconds until SIGTERM",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    if args.daemon:
        await run_daemon(args.cohort, args.interval)
    else:
        await run_one_shot(args.cohort, args.count)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Daemon mode handles SIGINT via its event; one-shot raises here.
        logger.info("Interrupted; exiting.")
        sys.exit(130)
