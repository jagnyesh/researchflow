"""Phase 2.3 input validation framework.

Re-exports framework primitives for convenient import. Schemas themselves live
in submodules and require explicit `from app.schemas.X import Y` imports.

Usage:
    from app.schemas import PHIInputModel, ShortText, LongText, IRBNumber, BoundedDict, EmailStr
    from app.schemas.research import ResearchRequestSubmission   # actual schemas
"""

from ._base import PHIInputModel
from ._errors import phi_safe_validation_handler
from ._types import (
    BoundedDict,
    EmailStr,
    IRBNumber,
    LongText,
    MediumText,
    NonEmptyStr,
    ShortText,
    bound_dict_size,
)

__all__ = [
    "PHIInputModel",
    "phi_safe_validation_handler",
    "BoundedDict",
    "EmailStr",
    "IRBNumber",
    "LongText",
    "MediumText",
    "NonEmptyStr",
    "ShortText",
    "bound_dict_size",
]
