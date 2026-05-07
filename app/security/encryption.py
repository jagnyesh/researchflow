"""Encryption column-type factories — Sprint 6.1 Phase 3b.

Thin wrappers around `sqlalchemy_utils.StringEncryptedType` /
`EncryptedType` that fix the engine to `FernetEngine` and the key source to
`get_encryption_key()`. Models import these factories so column definitions
stay one-line and the encryption parameters live in one place.

`FernetEngine` is AES-128-CBC + HMAC-SHA256 with versioned ciphertext; the
version byte is what makes a future MultiFernet-based rotation envelope (see
`docs/HIPAA_POSTURE.md` Phase 3b rotation runbook) ergonomic without a
schema-aware backfill.
"""

from sqlalchemy import Text
from sqlalchemy_utils import StringEncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import FernetEngine

from .encryption_keys import get_encryption_key


def EncryptedText() -> StringEncryptedType:
    """Encrypted `Text` column for free-form PHI strings.

    Used on `ResearchRequest.initial_request`, `FeasibilityReport.phenotype_sql`,
    and any other PHI-bearing free-form text column.
    """
    return StringEncryptedType(Text, get_encryption_key, FernetEngine)
