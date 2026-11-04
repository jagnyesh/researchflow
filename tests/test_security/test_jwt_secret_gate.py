"""#279: no JWT is signed or verified in production with the default secret.

The check sits on the sign/verify path, so Streamlit and scripts that import
app.security.auth are covered without their own start-up hook.
"""

import pytest

from app.security.auth import create_access_token, decode_access_token

CLAIMS = {"sub": "researcher@example.org", "user_id": "USR-1", "role": "researcher"}


def test_signing_refuses_in_production_when_secret_unset(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        create_access_token(CLAIMS)


def test_signing_refuses_in_production_with_the_default_secret(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        create_access_token(CLAIMS)


def test_verifying_refuses_in_production_with_the_default_secret(monkeypatch):
    # A token forged with the public default must not verify once deployed.
    monkeypatch.setenv("ENVIRONMENT", "development")
    forged = create_access_token(CLAIMS)
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        decode_access_token(forged)


def test_production_round_trip_with_a_real_secret(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "a-real-deployment-secret-0123456789")

    assert decode_access_token(create_access_token(CLAIMS)).role == "researcher"


def test_development_still_works_without_a_secret(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    assert decode_access_token(create_access_token(CLAIMS)).email == CLAIMS["sub"]


@pytest.mark.asyncio
async def test_api_refuses_to_start_in_production_with_the_default_secret(monkeypatch):
    from cryptography.fernet import Fernet

    from app.main import app, lifespan

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ENCRYPTION_KEY_PRIMARY", Fernet.generate_key().decode())
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("REDIS_AUDIT_URL", raising=False)

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        async with lifespan(app):
            pass
