"""Base class for the Phase 2.3 input validation framework.

PHIInputModel is the base for any request body that may carry PHI or that flows
into PHI-handling code paths. The config defaults are deliberately strict —
schemas opt out per-field if they need looser behavior.
"""

from pydantic import BaseModel, ConfigDict


class PHIInputModel(BaseModel):
    """Strict-by-default base for PHI-relevant request bodies.

    Config rationale:
    - `extra='forbid'`: an attacker submitting `{"sql": "SELECT 1", "is_admin": true}`
      to SQLQueryRequest gets 422, not silent acceptance with downstream code maybe
      reading the unexpected key. Defends against future field additions where some
      consumer starts reading a key before the schema catches up.
    - `str_strip_whitespace=True`: normalize before constraint checks; means
      `"  IRB-001  "` is accepted as `"IRB-001"`.
    - `validate_assignment=True`: re-validates on attribute set so post-construction
      mutations can't bypass constraints.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )
