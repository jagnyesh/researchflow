"""Typed primitives for the Phase 2.3 input validation framework.

These are reused across all per-router schema files in app/schemas/.
"""

from typing import Annotated, Any, Dict

from pydantic import BeforeValidator, EmailStr, Field

# Re-export EmailStr for convenience: callers do `from app.schemas._types import EmailStr`
__all__ = [
    "NonEmptyStr",
    "ShortText",
    "MediumText",
    "LongText",
    "IRBNumber",
    "BoundedDict",
    "EmailStr",
    "bound_dict_size",
]

# String length conventions. Generous enough not to false-reject legitimate input;
# tight enough to block JSON bombs and DoS-via-1MB-body.
NonEmptyStr = Annotated[str, Field(min_length=1)]
ShortText = Annotated[str, Field(max_length=200)]
MediumText = Annotated[str, Field(max_length=2000)]
LongText = Annotated[str, Field(max_length=50000)]

# Permissive IRB regex — supports institutional variation. Tested fixture formats:
# IRB-001, IRB-2024-001, IRB-2024-HF-001, IRB-2025-001, IRB-2025-E2E-TEST-001 — all pass.
# Sales-grade HIPAA targets multiple institutions; forcing canonical format closes
# doors during pilot conversations.
IRBNumber = Annotated[
    str,
    Field(pattern=r"^IRB[-/_]?[A-Z0-9-/_]+$", max_length=50),
]


def bound_dict_size(
    value: Any,
    max_keys: int = 100,
    max_depth: int = 5,
    max_leaf_str: int = 10_000,
) -> Any:
    """Reject dicts with too many keys, too-deep nesting, or oversized leaf strings.

    Walks both nested dicts and lists. Strings at any leaf position are bounded
    by max_leaf_str (default 10KB) — without this, a single dict with one giant
    string value bypasses LongText caps and causes memory exhaustion (CSO Phase 2.3
    Finding 1: combined with no body-size limit, this is a real DoS vector).

    Non-dict top-level input passes through unchanged so Pydantic's normal type
    check runs (and fails appropriately).
    """
    if not isinstance(value, dict):
        return value

    def _walk(v: Any, depth: int = 0) -> None:
        if depth > max_depth:
            raise ValueError(f"dict depth exceeds max_depth={max_depth}")
        if isinstance(v, dict):
            if len(v) > max_keys:
                raise ValueError(f"dict has {len(v)} keys, max_keys={max_keys}")
            for sub in v.values():
                _walk(sub, depth + 1)
        elif isinstance(v, list):
            for sub in v:
                _walk(sub, depth + 1)
        elif isinstance(v, str):
            if len(v) > max_leaf_str:
                raise ValueError(f"leaf string has {len(v)} chars, max_leaf_str={max_leaf_str}")

    _walk(value)
    return value


BoundedDict = Annotated[Dict[str, Any], BeforeValidator(bound_dict_size)]
