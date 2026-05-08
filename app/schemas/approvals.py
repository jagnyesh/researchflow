"""Schemas for /approvals router — Sprint 6.1 Phase 2.3 Issue #5 (Tier 1)."""

from typing import Literal, Optional

from app.schemas import (
    BoundedDict,
    EmailStr,
    MediumText,
    PHIInputModel,
    ShortText,
)


class ApprovalResponse(PHIInputModel):
    """Body for POST /approvals/{approval_id}/respond.

    Despite the name, this is a request body (the human's response to an
    approval prompt). Kept as `ApprovalResponse` for API back-compat.
    """

    decision: Literal["approve", "reject", "modify"]
    reviewer: ShortText
    notes: Optional[MediumText] = None
    modifications: Optional[BoundedDict] = None


class ScopeChangeRequest(PHIInputModel):
    """Body for POST /approvals/scope-change."""

    request_id: ShortText
    requested_by: EmailStr
    requested_changes: BoundedDict
    reason: Optional[MediumText] = None
