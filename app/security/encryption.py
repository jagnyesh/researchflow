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

import json

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator
from sqlalchemy_utils import StringEncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import FernetEngine

from .encryption_keys import get_encryption_key


def EncryptedText() -> StringEncryptedType:
    """Encrypted `Text` column for free-form PHI strings.

    Used on `ResearchRequest.initial_request`, `FeasibilityReport.phenotype_sql`,
    and any other PHI-bearing free-form text column.
    """
    return StringEncryptedType(Text, get_encryption_key, FernetEngine)


class _EncryptedJSONImpl(TypeDecorator):
    """JSON values stored as encrypted Text — workaround for the
    `EncryptedType(JSON)` round-trip bug.

    `sqlalchemy_utils.EncryptedType.process_result_value` decrypts to a string
    and then calls `self.underlying_type.python_type(decrypted_value)`. For
    `JSON`, `python_type` is `dict`, so the call becomes
    `dict("[{...JSON-string...}]")` — which raises
    `ValueError: dictionary update sequence element #0 has length 1; 2 is required`.
    The library never calls `json.loads` on the decrypted string.

    We sidestep the bug by storing JSON as encrypted text and handling the
    `dumps` / `loads` boundary at the column-type layer, so models still see a
    clean Python dict/list and never know about the encryption.
    """

    impl = StringEncryptedType
    cache_ok = True

    def __init__(self):
        super().__init__(Text, get_encryption_key, FernetEngine)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None or value == "":
            return None
        return json.loads(value)


def EncryptedJSON() -> _EncryptedJSONImpl:
    """Encrypted JSON column for structured PHI dicts/lists.

    Underlying storage is BYTEA (Postgres) / BLOB (SQLite). JSONB query
    operators (`->>`, `@>`) are NOT available — only wholesale ORM round-trip
    reads. Confirmed via `grep -rn "->>"` in `app/` that none of the
    encryption-targeted JSON columns use JSONB ops; all JSONB usage targets
    HAPI's `res_text_vc::jsonb` (a separate database).

    Used on `RequirementsData.inclusion_criteria` /
    `RequirementsData.exclusion_criteria`.
    """
    return _EncryptedJSONImpl()
