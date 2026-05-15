"""Sprint 6.4 cycle 5 — Detection mechanism for materialized view health.

After each successful materialization, query HAPI oracle for the expected
row count and compare against the MV's actual row count. Log a structured
JSONL record to `logs/mv_health.jsonl`. If the same MV reports `warn`
status on N=3 consecutive runs, fire a WARN-level log (alarm filter).

Per Sprint 6.4 #40 D3 locked decisions:
  - Same-run oracle (data-drift-immune): query HAPI and MV at the same
    materialization moment
  - Per-run threshold: |actual - oracle| / oracle > 5% → "warn"
  - Alarm filter: 3 consecutive "warn" records before alarm fires
  - Output: logs/mv_health.jsonl (one JSON record per check)
  - Surfaced in admin dashboard "💰 Cost Telemetry" tab (cycle 6 scope)

This file covers the unit-testable helpers + end-to-end integration test
(requires_hapi-gated). The actual wiring into ViewMaterializer happens
after these tests pass.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from app.sql_on_fhir.runner.mv_health_check import (
    check_alarm,
    load_oracle_query,
    make_health_record,
    read_recent_health_records,
)


# ---------------------------------------------------------------------------
# load_oracle_query — parses tests/fixtures/mv_row_count_oracles.sql
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "view_name,expected_substring",
    [
        ("condition_diagnoses", "AS condition_diagnoses_oracle"),
        ("observation_labs", "AS observation_labs_oracle"),
        ("procedure_history", "AS procedure_history_oracle"),
    ],
)
def test_load_oracle_query_returns_select_for_known_view(view_name, expected_substring):
    """load_oracle_query() extracts the SELECT statement for a known MV.

    The oracle SQL file is the source of truth (documented WHERE-clause
    replication + data observations). This parser pulls the executable
    SELECT for runtime use without duplicating the SQL in Python.
    """
    query = load_oracle_query(view_name)
    assert query is not None, f"oracle query for {view_name} should be parseable"
    assert "SELECT" in query.upper()
    assert expected_substring in query
    assert query.rstrip().endswith(";"), "extracted query must include terminating semicolon"


def test_load_oracle_query_returns_none_for_unknown_view():
    """Unknown view_name → None (caller decides whether that's an error)."""
    assert load_oracle_query("nonexistent_view") is None


# ---------------------------------------------------------------------------
# make_health_record — pure status logic
# ---------------------------------------------------------------------------


def test_make_health_record_status_ok_when_delta_under_threshold():
    """5% threshold: 4.99% delta → status='ok'."""
    record = make_health_record(
        view_name="condition_diagnoses",
        actual_count=14000,
        oracle_count=14732,  # 4.97% off
        threshold_pct=5.0,
    )
    assert record["status"] == "ok"
    assert record["view_name"] == "condition_diagnoses"
    assert record["actual_count"] == 14000
    assert record["oracle_count"] == 14732
    assert "delta_pct" in record
    assert abs(record["delta_pct"] - 4.97) < 0.01
    assert "ts" in record
    assert "git_commit" in record


def test_make_health_record_status_warn_when_delta_above_threshold():
    """5% threshold: 5.01% delta → status='warn'."""
    record = make_health_record(
        view_name="observation_labs",
        actual_count=149400,
        oracle_count=157689,  # 5.26% off
        threshold_pct=5.0,
    )
    assert record["status"] == "warn"
    assert abs(record["delta_pct"] - 5.26) < 0.01


def test_make_health_record_exact_zero_delta():
    """0% delta → status='ok' with delta_pct=0.0."""
    record = make_health_record(
        view_name="procedure_history",
        actual_count=66448,
        oracle_count=66448,
        threshold_pct=5.0,
    )
    assert record["status"] == "ok"
    assert record["delta_pct"] == 0.0


def test_make_health_record_oracle_zero_treated_as_warn():
    """If oracle is 0 (e.g., parser returned a count of 0 unexpectedly),
    treat as warn rather than crash on divide-by-zero. The whole point
    of the check is to surface anomalies; an unexpected zero oracle IS
    an anomaly worth alarming on.
    """
    record = make_health_record(
        view_name="x",
        actual_count=100,
        oracle_count=0,
        threshold_pct=5.0,
    )
    assert record["status"] == "warn"


# ---------------------------------------------------------------------------
# check_alarm — consecutive-runs filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "recent_statuses,expected_alarm",
    [
        # 0 records → no alarm (insufficient signal)
        ([], False),
        # 1 warn → no alarm (single-run noise filter)
        (["warn"], False),
        # 2 consecutive warns → no alarm (still under N=3)
        (["warn", "warn"], False),
        # 3 consecutive warns → alarm fires
        (["warn", "warn", "warn"], True),
        # 4 records, last 3 warn → alarm fires (most recent 3 are bad)
        (["ok", "warn", "warn", "warn"], True),
        # 3 records but interleaved ok → no alarm (not consecutive)
        (["warn", "ok", "warn"], False),
        # 5 warns → alarm (≥3 most-recent are warn)
        (["warn"] * 5, True),
        # 3 oks → no alarm
        (["ok", "ok", "ok"], False),
    ],
)
def test_check_alarm_consecutive_runs_filter(tmp_path, recent_statuses, expected_alarm):
    """Alarm fires only if the last N=3 records for the view are all 'warn'.

    Filters single-run noise. Uses a temp JSONL file isolated per test so
    runs don't bleed into each other.
    """
    log_path = tmp_path / "mv_health.jsonl"
    view_name = "test_view"
    # Write each status as a separate JSONL record
    for i, status in enumerate(recent_statuses):
        record = {
            "ts": f"2026-05-15T17:{i:02d}:00+00:00",
            "view_name": view_name,
            "actual_count": 100,
            "oracle_count": 100,
            "delta_pct": 0.0,
            "status": status,
            "git_commit": "abc1234",
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(record) + "\n")

    assert check_alarm(view_name, n_runs=3, log_path=log_path) is expected_alarm


def test_check_alarm_ignores_other_view_records(tmp_path):
    """check_alarm() filters by view_name — other views' records don't count."""
    log_path = tmp_path / "mv_health.jsonl"
    # 3 warns on other_view + 1 ok on target_view → no alarm for target_view
    for status, view in [("warn", "other"), ("warn", "other"), ("warn", "other"), ("ok", "target")]:
        record = {
            "ts": "2026-05-15T17:00:00+00:00",
            "view_name": view,
            "actual_count": 100,
            "oracle_count": 100,
            "delta_pct": 0.0,
            "status": status,
            "git_commit": "abc1234",
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(record) + "\n")

    assert check_alarm("target", n_runs=3, log_path=log_path) is False
    assert check_alarm("other", n_runs=3, log_path=log_path) is True


def test_check_alarm_returns_false_when_log_file_missing(tmp_path):
    """No log file → no alarm (cold-start case)."""
    log_path = tmp_path / "does_not_exist.jsonl"
    assert check_alarm("any_view", n_runs=3, log_path=log_path) is False


# ---------------------------------------------------------------------------
# read_recent_health_records — dashboard reader (cycle 6)
# ---------------------------------------------------------------------------


def test_read_recent_health_records_returns_last_n_in_file_order(tmp_path):
    """Returns the last N records across all views, newest-LAST (file order
    preserved so the dashboard can render chronologically).

    Cycle 6 surfaces these in the admin Cost Telemetry tab. The reader is a
    pure helper — Streamlit reads it, formats as a dataframe, no business
    logic in the UI layer.
    """
    log_path = tmp_path / "mv_health.jsonl"
    # 5 records, mixed views, sequential timestamps
    fixtures = [
        ("2026-05-15T10:00:00+00:00", "condition_diagnoses", "ok"),
        ("2026-05-15T10:01:00+00:00", "observation_labs", "ok"),
        ("2026-05-15T10:02:00+00:00", "procedure_history", "warn"),
        ("2026-05-15T10:03:00+00:00", "condition_diagnoses", "ok"),
        ("2026-05-15T10:04:00+00:00", "observation_labs", "warn"),
    ]
    for ts, view_name, status in fixtures:
        record = {
            "ts": ts,
            "view_name": view_name,
            "actual_count": 100,
            "oracle_count": 100,
            "delta_pct": 0.0,
            "status": status,
            "git_commit": "abc1234",
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(record) + "\n")

    # n=3 → return the last 3 records in file order
    records = read_recent_health_records(n=3, log_path=log_path)
    assert len(records) == 3
    assert records[0]["ts"] == "2026-05-15T10:02:00+00:00"
    assert records[1]["ts"] == "2026-05-15T10:03:00+00:00"
    assert records[2]["ts"] == "2026-05-15T10:04:00+00:00"
    assert records[2]["view_name"] == "observation_labs"
    assert records[2]["status"] == "warn"


def test_read_recent_health_records_returns_empty_when_log_missing(tmp_path):
    """Cold-start: no file → empty list (dashboard renders 'no data' message)."""
    log_path = tmp_path / "does_not_exist.jsonl"
    assert read_recent_health_records(n=10, log_path=log_path) == []


def test_read_recent_health_records_returns_all_when_n_exceeds_count(tmp_path):
    """n larger than total → return everything in file order. Streamlit
    requests n=20; cold-warm dashboards have <20 records and should still render.
    """
    log_path = tmp_path / "mv_health.jsonl"
    # Only 2 records exist
    for i in range(2):
        record = {
            "ts": f"2026-05-15T10:0{i}:00+00:00",
            "view_name": "x",
            "actual_count": 1,
            "oracle_count": 1,
            "delta_pct": 0.0,
            "status": "ok",
            "git_commit": "abc1234",
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(record) + "\n")

    records = read_recent_health_records(n=20, log_path=log_path)
    assert len(records) == 2
    assert records[0]["ts"] == "2026-05-15T10:00:00+00:00"
    assert records[1]["ts"] == "2026-05-15T10:01:00+00:00"


def test_read_recent_health_records_tolerates_corrupt_lines(tmp_path):
    """Defense in depth: a malformed JSONL line is skipped, not raised.
    The dashboard should never crash because one line got corrupted by
    a partial-write or external editor.
    """
    log_path = tmp_path / "mv_health.jsonl"
    with open(log_path, "w") as f:
        f.write(json.dumps({"ts": "t1", "view_name": "x", "status": "ok"}) + "\n")
        f.write("not valid json at all\n")
        f.write(json.dumps({"ts": "t2", "view_name": "y", "status": "warn"}) + "\n")

    records = read_recent_health_records(n=10, log_path=log_path)
    assert len(records) == 2
    assert records[0]["ts"] == "t1"
    assert records[1]["ts"] == "t2"
