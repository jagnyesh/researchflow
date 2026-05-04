"""Schemas for /a2a router — Sprint 6.1 Phase 2.3 Issue #6 (Tier 2)."""

from typing import Annotated

from pydantic import Field

from app.schemas import PHIInputModel


# Service-token credentials: bounded length, non-empty.
ServiceCredential = Annotated[str, Field(min_length=1, max_length=200)]


class TokenRequest(PHIInputModel):
    """Body for POST /a2a/token (service-token issuance)."""

    client_id: ServiceCredential
    client_secret: ServiceCredential
