"""Phase 3b — encryption-at-rest: model column round-trip + ciphertext-on-disk."""

from datetime import datetime

import pytest
from sqlalchemy import text

from app.database import get_db_session, get_engine
from app.database.models import ResearchRequest

PHI_PLAINTEXT = "patient ABC-123 has HbA1c 9.2% on 2025-12-04, needs DM2 cohort"


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

    assert raw is not None
    assert raw != PHI_PLAINTEXT
    assert PHI_PLAINTEXT not in (
        raw if isinstance(raw, str) else raw.decode("latin-1", errors="replace")
    )
