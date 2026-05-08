"""Schemas for /mcp router — Sprint 6.1 Phase 2.3 Issue #5 (Tier 1)."""

from app.schemas import BoundedDict, PHIInputModel, ShortText


class ContextRequest(PHIInputModel):
    """Body for POST /mcp/context. Carries arbitrary agent context — bound the size."""

    request_id: ShortText
    context: BoundedDict
