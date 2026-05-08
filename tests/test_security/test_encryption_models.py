"""Phase 3b — encryption-at-rest: model column round-trip + ciphertext-on-disk."""

import json
from datetime import datetime

import pytest
from sqlalchemy import text

from app.database import get_db_session, get_engine
from app.database.models import FeasibilityReport, RequirementsData, ResearchRequest

PHI_PLAINTEXT = "patient ABC-123 has HbA1c 9.2% on 2025-12-04, needs DM2 cohort"


async def _seed_parent_request(rid: str) -> None:
    """Insert a minimal ResearchRequest so FK-bound rows can attach."""
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=rid,
                researcher_name="Dr. Smith",
                researcher_email="smith@example.edu",
                initial_request="parent-request placeholder",
                current_state="initiated",
            )
        )
        await session.commit()


async def _read_raw(table: str, column: str, rid_field: str, rid: str):
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(f"SELECT {column} FROM {table} WHERE {rid_field} = :id"),
            {"id": rid},
        )
        return result.scalar_one()


def _ciphertext_excludes_plaintext(raw, plaintext: str) -> None:
    assert raw is not None
    assert raw != plaintext
    decoded = raw if isinstance(raw, str) else raw.decode("latin-1", errors="replace")
    assert plaintext not in decoded


@pytest.mark.asyncio
async def test_initial_request_round_trips_through_orm(clean_database):
    rid = "REQ-20260507-ENCRYPT0"

    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=rid,
                researcher_name="Dr. Smith",
                researcher_email="smith@example.edu",
                initial_request=PHI_PLAINTEXT,
                current_state="initiated",
            )
        )
        await session.commit()

    async with get_db_session() as session:
        row = await session.get(ResearchRequest, rid)
        assert row is not None
        assert row.initial_request == PHI_PLAINTEXT


@pytest.mark.asyncio
async def test_initial_request_is_ciphertext_on_disk(clean_database):
    rid = "REQ-20260507-ENCRYPT1"

    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=rid,
                researcher_name="Dr. Smith",
                researcher_email="smith@example.edu",
                initial_request=PHI_PLAINTEXT,
                current_state="initiated",
            )
        )
        await session.commit()

    # Bypass the ORM column type and read the raw bytes the DB actually stored.
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT initial_request FROM research_requests WHERE id = :id"),
            {"id": rid},
        )
        raw = result.scalar_one()

    _ciphertext_excludes_plaintext(raw, PHI_PLAINTEXT)


# ---- Issue #9 — RequirementsData.inclusion_criteria (JSON list) -----------


@pytest.mark.asyncio
async def test_inclusion_criteria_round_trips_through_orm(clean_database):
    rid = "REQ-20260507-INC0"
    await _seed_parent_request(rid)

    payload = [
        {"icd10": "E11.9", "label": "Type 2 DM, MRN-12345 cohort"},
        {"icd10": "E10", "label": "exclude T1DM"},
    ]
    async with get_db_session() as session:
        session.add(RequirementsData(request_id=rid, inclusion_criteria=payload))
        await session.commit()

    async with get_db_session() as session:
        result = await session.execute(
            text("SELECT id FROM requirements_data WHERE request_id = :id"),
            {"id": rid},
        )
        row_id = result.scalar_one()
        row = await session.get(RequirementsData, row_id)

    assert row.inclusion_criteria == payload


@pytest.mark.asyncio
async def test_inclusion_criteria_is_ciphertext_on_disk(clean_database):
    rid = "REQ-20260507-INC1"
    await _seed_parent_request(rid)

    needle = "MRN-99999-secret-cohort-criterion"
    payload = [{"icd10": "E11.9", "label": needle}]

    async with get_db_session() as session:
        session.add(RequirementsData(request_id=rid, inclusion_criteria=payload))
        await session.commit()

    raw = await _read_raw("requirements_data", "inclusion_criteria", "request_id", rid)
    _ciphertext_excludes_plaintext(raw, needle)
    # JSON-shape leakage check: raw stored bytes should not contain the JSON
    # serialization of the payload either.
    _ciphertext_excludes_plaintext(raw, json.dumps(payload))


# ---- Issue #9 — RequirementsData.exclusion_criteria (JSON list) -----------


@pytest.mark.asyncio
async def test_exclusion_criteria_round_trips_and_is_ciphertext_on_disk(clean_database):
    rid = "REQ-20260507-EXC0"
    await _seed_parent_request(rid)

    needle = "patient-DOB-1947-03-22-must-not-leak"
    payload = [{"icd10": "E10", "label": needle}]

    async with get_db_session() as session:
        session.add(RequirementsData(request_id=rid, exclusion_criteria=payload))
        await session.commit()

    async with get_db_session() as session:
        row_id = (
            await session.execute(
                text("SELECT id FROM requirements_data WHERE request_id = :id"),
                {"id": rid},
            )
        ).scalar_one()
        row = await session.get(RequirementsData, row_id)
    assert row.exclusion_criteria == payload

    raw = await _read_raw("requirements_data", "exclusion_criteria", "request_id", rid)
    _ciphertext_excludes_plaintext(raw, needle)
    _ciphertext_excludes_plaintext(raw, json.dumps(payload))


# ---- Issue #9 — FeasibilityReport.phenotype_sql (Text) -------------------


@pytest.mark.asyncio
async def test_phenotype_sql_round_trips_and_is_ciphertext_on_disk(clean_database):
    rid = "REQ-20260507-SQL0"
    await _seed_parent_request(rid)

    sql = "SELECT * FROM patient WHERE family_name = 'Patient-Doe-MRN-555-1234'"

    async with get_db_session() as session:
        session.add(
            FeasibilityReport(
                request_id=rid,
                is_feasible=True,
                feasibility_score=0.9,
                phenotype_sql=sql,
            )
        )
        await session.commit()

    async with get_db_session() as session:
        row_id = (
            await session.execute(
                text("SELECT id FROM feasibility_reports WHERE request_id = :id"),
                {"id": rid},
            )
        ).scalar_one()
        row = await session.get(FeasibilityReport, row_id)
    assert row.phenotype_sql == sql

    raw = await _read_raw("feasibility_reports", "phenotype_sql", "request_id", rid)
    _ciphertext_excludes_plaintext(raw, sql)
    _ciphertext_excludes_plaintext(raw, "Patient-Doe-MRN-555-1234")
