"""Schemas for /research router — Sprint 6.1 Phase 2.3 Issue #5 (Tier 1)."""

from typing import Optional

from app.schemas import (
    BoundedDict,
    EmailStr,
    IRBNumber,
    LongText,
    PHIInputModel,
    ShortText,
)


class ResearchRequestSubmission(PHIInputModel):
    """Body for POST /research/submit."""

    researcher_name: ShortText
    researcher_email: EmailStr
    researcher_department: Optional[ShortText] = None
    irb_number: IRBNumber
    initial_request: LongText
    structured_requirements: Optional[BoundedDict] = None


class RequestProcessingTrigger(PHIInputModel):
    """Body for POST /research/process/{request_id}."""

    structured_requirements: Optional[BoundedDict] = None
    skip_conversation: bool = False
