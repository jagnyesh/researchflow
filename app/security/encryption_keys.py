"""Encryption key sourcing — Sprint 6.1 Phase 3b.

`get_encryption_key()` is the pluggable key callable passed to
`StringEncryptedType` / `EncryptedType` columns. The default implementation
reads the `ENCRYPTION_KEY_PRIMARY` env var; institutions that mandate KMS or
Vault swap this function body at deploy time without touching column
definitions.
"""

import os


def _is_production() -> bool:
    """Strict equality, case-sensitive — same posture as `tls.is_production()`.

    A typo (`Production`, trailing space, etc.) gets dev behavior. Never
    accidentally fail-closed on a developer's laptop.
    """
    return os.getenv("ENVIRONMENT", "development") == "production"


def assert_encryption_key_present_if_production() -> None:
    """No-op outside production; raises in production if the key is missing or malformed.

    Called from `app/main.py` lifespan startup. Failure exits the process
    non-zero (uvicorn surfaces the RuntimeError) so the container restart loop
    advertises the misconfiguration loudly.
    """
    if not _is_production():
        return

    key = os.getenv("ENCRYPTION_KEY_PRIMARY")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY_PRIMARY is required in production. "
            "Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'"
        )

    from cryptography.fernet import Fernet

    try:
        Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError(
            f"ENCRYPTION_KEY_PRIMARY is set but is not a valid Fernet key: {exc}. "
            "Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'"
        ) from exc


def get_encryption_key() -> bytes:
    """Return the active Fernet key as bytes.

    Reads `ENCRYPTION_KEY_PRIMARY` from the environment. The startup gate
    (`assert_encryption_key_present_if_production`) is responsible for refusing
    to start the app in production when the env var is missing or malformed —
    this function trusts the gate's pre-check and just returns what it finds.
    """
    return os.environ["ENCRYPTION_KEY_PRIMARY"].encode()
