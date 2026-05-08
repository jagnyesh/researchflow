"""Schemas for /analytics router — Sprint 6.1 Phase 2.3 Issue #5 (Tier 1)."""

from typing import Optional

from app.schemas import BoundedDict, PHIInputModel, ShortText


class ViewDefinitionRequest(PHIInputModel):
    """Body for POST /analytics/execute."""

    view_name: ShortText
    search_params: Optional[BoundedDict] = None
    max_resources: Optional[int] = None


class CreateViewDefinitionRequest(PHIInputModel):
    """Body for POST /analytics/view-definitions."""

    view_definition: BoundedDict
    name: Optional[ShortText] = None


class CountRequest(PHIInputModel):
    """Body for POST /analytics/count."""

    view_name: ShortText
    search_params: Optional[BoundedDict] = None
