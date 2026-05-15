"""Sprint 6.4 cycle 5 — Materialized View health-check detection mechanism.

After each successful materialization, query HAPI oracle and the MV's
actual row count at the same materialization run (same-instant,
data-drift-immune per D3 locked decision). Log a structured JSONL
record. If the same MV reports `warn` status on N=3 consecutive runs,
fire an alarm via WARN-level log (filters single-run noise).

Public surface (deep module per /tdd skill — one entry point,
several testable helpers):

  - `post_write_health_check(conn, view_name, actual_count) -> dict`
    Top-level entry called from ViewMaterializer after each successful
    materialize. Composes the helpers below into one async call.

  - `load_oracle_query(view_name) -> Optional[str]`
    Parses tests/fixtures/mv_row_count_oracles.sql; returns the SELECT
    statement for a known view_name or None for unknowns.

  - `measure_oracle_count(conn, view_name) -> Optional[int]`
    Runs the parsed SELECT against `conn`. Returns the count or None
    if no oracle is defined for view_name.

  - `make_health_record(view_name, actual, oracle, threshold_pct) -> dict`
    Pure status logic. status="ok" if |delta|/oracle <= threshold_pct,
    else "warn". Treats oracle=0 as warn (the whole point is to surface
    anomalies; unexpected zero IS an anomaly).

  - `append_health_record(record, log_path) -> None`
    JSONL writer. Creates parent dirs + file if absent.

  - `check_alarm(view_name, n_runs=3, log_path=...) -> bool`
    Reads recent records for `view_name`; returns True if the last
    n_runs are all "warn". Cold-start (no file) returns False.

Surfaced into the admin dashboard "💰 Cost Telemetry" tab in cycle 6.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess  # nosec B404 — fixed-arg `git rev-parse --short HEAD` only; see _current_git_commit
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)

# Resolve repo root from this file: app/sql_on_fhir/runner/mv_health_check.py
# parents: runner → sql_on_fhir → app → repo_root
_REPO_ROOT = Path(__file__).resolve().parents[3]

ORACLES_SQL_PATH = _REPO_ROOT / "tests" / "fixtures" / "mv_row_count_oracles.sql"
DEFAULT_LOG_PATH = _REPO_ROOT / "logs" / "mv_health.jsonl"

DEFAULT_THRESHOLD_PCT = 5.0
DEFAULT_ALARM_CONSECUTIVE_RUNS = 3


def load_oracle_query(view_name: str) -> Optional[str]:
    """Parse mv_row_count_oracles.sql and return the SELECT for view_name.

    The .sql file has section headers like:
        -- ============================================================
        -- <view_name>
        -- ============================================================
        ... comments ...
        SELECT ... ;

    This regex captures the SELECT statement following the named header.
    """
    if not ORACLES_SQL_PATH.exists():
        return None
    text = ORACLES_SQL_PATH.read_text()
    # Find `-- <view_name>` on its own line, then capture the next SELECT...;
    pattern = rf"^-- {re.escape(view_name)}\s*\n[\s\S]*?(SELECT[\s\S]+?;)"
    m = re.search(pattern, text, flags=re.MULTILINE)
    if m:
        return m.group(1)
    return None


async def measure_oracle_count(conn: asyncpg.Connection, view_name: str) -> Optional[int]:
    """Execute the oracle SQL for view_name and return the count.

    Returns None when the view_name has no oracle defined — caller
    decides whether that's an error or expected (e.g., custom-path MVs
    don't have oracles in cycle 5 scope).
    """
    query = load_oracle_query(view_name)
    if query is None:
        return None
    return await conn.fetchval(query)


def make_health_record(
    view_name: str,
    actual_count: int,
    oracle_count: int,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
) -> Dict[str, Any]:
    """Construct a health-check record. Status = 'ok' if |delta|/oracle ≤
    threshold_pct, else 'warn'. Oracle=0 is treated as 'warn' (unexpected
    zero IS an anomaly worth alarming on; avoids divide-by-zero crash too).
    """
    if oracle_count == 0:
        delta_pct = 0.0 if actual_count == 0 else 100.0
        status = "warn"
    else:
        delta_pct = abs(actual_count - oracle_count) / oracle_count * 100
        status = "ok" if delta_pct <= threshold_pct else "warn"

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "view_name": view_name,
        "actual_count": actual_count,
        "oracle_count": oracle_count,
        "delta_pct": round(delta_pct, 4),
        "status": status,
        "git_commit": _current_git_commit(),
    }


def append_health_record(
    record: Dict[str, Any],
    log_path: Path = DEFAULT_LOG_PATH,
) -> None:
    """Append one JSON record to log_path. Creates parent dirs if absent."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")


def check_alarm(
    view_name: str,
    n_runs: int = DEFAULT_ALARM_CONSECUTIVE_RUNS,
    log_path: Path = DEFAULT_LOG_PATH,
) -> bool:
    """Return True if the last n_runs records for view_name are all 'warn'.

    Filters single-run noise. Cold-start (log file missing) returns False.
    """
    if not log_path.exists():
        return False

    records_for_view = _read_recent_records_for_view(log_path, view_name)
    if len(records_for_view) < n_runs:
        return False

    last_n = records_for_view[-n_runs:]
    return all(r.get("status") == "warn" for r in last_n)


async def post_write_health_check(
    conn: asyncpg.Connection,
    view_name: str,
    actual_count: int,
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    n_runs_for_alarm: int = DEFAULT_ALARM_CONSECUTIVE_RUNS,
    log_path: Path = DEFAULT_LOG_PATH,
) -> Optional[Dict[str, Any]]:
    """Run the oracle, build the record, append, check alarm.

    Returns the record dict, or None if no oracle is defined for view_name
    (e.g., the 4 custom-path MVs in cycle 5 scope — they have no oracle
    in mv_row_count_oracles.sql, so the health check is a no-op for them).

    If the alarm fires, logs a WARN-level message naming the view.
    Callers can read the returned record to decide further action.
    """
    oracle_count = await measure_oracle_count(conn, view_name)
    if oracle_count is None:
        logger.debug("mv_health: no oracle defined for %r — skipping health check", view_name)
        return None

    record = make_health_record(
        view_name=view_name,
        actual_count=actual_count,
        oracle_count=oracle_count,
        threshold_pct=threshold_pct,
    )
    append_health_record(record, log_path=log_path)

    if record["status"] == "warn":
        logger.info(
            "mv_health: %r delta %.2f%% > %s%% threshold (actual=%d, oracle=%d)",
            view_name,
            record["delta_pct"],
            threshold_pct,
            actual_count,
            oracle_count,
        )

    if check_alarm(view_name, n_runs=n_runs_for_alarm, log_path=log_path):
        logger.warning(
            "🚨 mv_health ALARM: %r has reported 'warn' status on %d consecutive "
            "runs. Most recent delta: %.2f%% (actual=%d, oracle=%d).",
            view_name,
            n_runs_for_alarm,
            record["delta_pct"],
            actual_count,
            oracle_count,
        )

    return record


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _read_recent_records_for_view(log_path: Path, view_name: str) -> List[Dict[str, Any]]:
    """Return all records for view_name in file order (oldest first)."""
    records: List[Dict[str, Any]] = []
    with open(log_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate corrupt lines
            if rec.get("view_name") == view_name:
                records.append(rec)
    return records


def _current_git_commit() -> str:
    """Return short SHA of HEAD, or 'unknown' if not in a git repo."""
    try:
        # nosec B603,B607 — argv list (no shell), fixed args, no user input;
        # `git` resolved via PATH is acceptable for a non-PHI annotation field.
        result = subprocess.run(  # noqa: S603,S607
            ["git", "rev-parse", "--short", "HEAD"],  # nosec B603 B607
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"
