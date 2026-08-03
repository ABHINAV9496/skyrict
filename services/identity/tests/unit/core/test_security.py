"""Unit tests for security utilities — JWT (RS256) and password hashing (Argon2id).

Includes adversarial tests: expired / wrong-issuer / wrong-audience / future-nbf
tokens, alg:none forgery, HS256 algorithm-confusion with the public key, tokens
signed by a foreign keypair, and missing required claims. Covers every line of
``identity.core.security``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jose import jwt as jose_jwt

from identity.core.config import settings
from identity.core.exceptions import StartupError
from identity.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_jwt,
    verify_jwt_keys_usable,
    verify_password,
)
from skyrict_common.exceptions import TokenExpiredError, TokenInvalidError


# ---------------------------------------------------------------------------
# Helpers — craft JWTs to probe verify_jwt's validation logic
# ---------------------------------------------------------------------------
def _valid_claims(**overrides) -> dict:
    """Return a claims dict that verify_jwt accepts (correct iss/aud, valid exp)."""
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "sub": "user-123",
        "tenant_id": "tenant-456",
        "iss": settings.JWKS_ISSUER,
        "aud": settings.JWKS_AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": now + 900,
        "type": "access",
    }
    claims.update(overrides)
    return claims


def _sign(payload: dict, private_key_pem: str, algorithm: str = "RS256") -> str:
    """Sign claims with python-jose — used to build adversarial tokens."""
    return jose_jwt.encode(payload, private_key_pem, algorithm=algorithm)


def _generate_keypair() -> tuple[str, str]:
    """Generate a throwaway RSA keypair, returning (private_pem, public_pem)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _b64url(data: bytes) -> str:
    """Base64url-encode without padding (JWT segment format)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _bare_token(header: dict, payload: dict, signature: str = "") -> str:
    """Manually assemble a token without python-jose (for alg:none forgeries)."""
    h = _b64url(json.dumps(header).encode())
    p = _b64url(json.dumps(payload).encode())
    return f"{h}.{p}.{signature}"


def _hmac_token(payload: dict, secret: str) -> str:
    """Manually sign an HS256 token with an HMAC secret.

    python-jose's cryptography backend refuses to construct an HMAC key from an
    asymmetric PEM, so this builds the token directly — reproducing the real
    algorithm-confusion attack where the attacker uses the public key as the
    HMAC secret.
    """
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = (
        f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(payload).encode())}"
    )
    signature = _b64url(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest())
    return f"{signing_input}.{signature}"


# ---------------------------------------------------------------------------
# Password hashing — Argon2id
# ---------------------------------------------------------------------------
class TestPasswordHashing:
    """Test Argon2id password hashing."""

    def test_hash_password_returns_hash(self):
        hashed = hash_password("TestPassword123!")
        assert hashed != "TestPassword123!"
        assert len(hashed) > 0

    def test_hash_uses_argon2id_algorithm(self):
        hashed = hash_password("TestPassword123!")
        assert hashed.startswith("$argon2id$")

    def test_verify_password_correct(self):
        password = "MySecurePassword!1"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        hashed = hash_password("CorrectPassword!1")
        assert verify_password("WrongPassword!1", hashed) is False

    def test_verify_password_malformed_hash(self):
        # A corrupted/malformed stored hash must never raise — just return False.
        assert verify_password("Anything!1", "not-a-valid-argon2-hash") is False

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("SamePassword!1")
        h2 = hash_password("SamePassword!1")
        assert h1 != h2  # Argon2id uses a random salt per call

    def test_verify_password_empty_string(self):
        hashed = hash_password("Password123!")
        assert verify_password("", hashed) is False


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------
class TestJWTCreation:
    """Tokens are signed with RS256 and carry correct claims."""

    def test_access_token_claims(self):
        token = create_access_token("user-123", tenant_id="tenant-456")
        payload = verify_jwt(token)
        assert payload["sub"] == "user-123"
        assert payload["tenant_id"] == "tenant-456"
        assert payload["type"] == "access"
        assert payload["iss"] == settings.JWKS_ISSUER
        assert payload["aud"] == settings.JWKS_AUDIENCE
        assert payload["exp"] > payload["iat"]

    def test_access_token_ttl_is_configured_minutes(self):
        token = create_access_token("user-123", tenant_id="tenant-456")
        payload = verify_jwt(token)
        expected = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        assert payload["exp"] - payload["iat"] == expected

    def test_access_token_custom_expiry(self):
        token = create_access_token(
            "user-123", tenant_id="tenant-456", expires_delta=timedelta(minutes=5)
        )
        payload = verify_jwt(token)
        assert payload["exp"] - payload["iat"] == 300

    def test_access_token_extra_claims_embedded(self):
        token = create_access_token(
            "user-123",
            tenant_id="tenant-456",
            extra_claims={"role": "admin", "scope": "read:users"},
        )
        payload = verify_jwt(token)
        assert payload["role"] == "admin"
        assert payload["scope"] == "read:users"

    def test_refresh_token_claims(self):
        token = create_refresh_token("user-123", tenant_id="tenant-456")
        payload = verify_jwt(token)
        assert payload["sub"] == "user-123"
        assert payload["tenant_id"] == "tenant-456"
        assert payload["type"] == "refresh"

    def test_refresh_token_outlives_access_token(self):
        access = verify_jwt(create_access_token("user-123", tenant_id="tenant-456"))
        refresh = verify_jwt(create_refresh_token("user-123", tenant_id="tenant-456"))
        assert (refresh["exp"] - refresh["iat"]) > (access["exp"] - access["iat"])


# ---------------------------------------------------------------------------
# Basic verification
# ---------------------------------------------------------------------------
class TestJWTVerification:
    """Happy-path and basic rejection cases."""

    def test_verify_invalid_token(self):
        with pytest.raises(TokenInvalidError):
            verify_jwt("not.a.valid.token")

    def test_verify_tampered_token(self):
        token = create_access_token("user-123", tenant_id="tenant-456")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(TokenInvalidError):
            verify_jwt(tampered)

    def test_verify_expired_token(self):
        token = create_access_token(
            "user-123", tenant_id="tenant-456", expires_delta=timedelta(days=-1)
        )
        with pytest.raises(TokenExpiredError):
            verify_jwt(token)


# ---------------------------------------------------------------------------
# Adversarial — token forgery and algorithm confusion
# ---------------------------------------------------------------------------
class TestJWTAdversarial:
    """Attack vectors that must always be rejected."""

    def test_rejects_alg_none_forgery(self, rsa_private_key: str):
        token = _bare_token(
            {"alg": "none", "typ": "JWT"},
            {"sub": "user-123", "iss": settings.JWKS_ISSUER, "aud": settings.JWKS_AUDIENCE},
        )
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_rejects_missing_algorithm_header(self):
        # Header with no alg — the code must not default to trusting anything.
        token = _bare_token({"typ": "JWT"}, {"sub": "user-123"})
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_rejects_hs256_forged_with_public_key(self, rsa_public_key: str):
        # Algorithm-confusion: attacker signs with the PUBLIC key as the HMAC
        # secret. Any implementation that trusts the header would accept this.
        token = _hmac_token(_valid_claims(), rsa_public_key)
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_rejects_token_signed_by_foreign_key(self):
        other_private, _ = _generate_keypair()
        token = _sign(_valid_claims(), other_private, algorithm="RS256")
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_rejects_wrong_issuer(self, rsa_private_key: str):
        token = _sign(_valid_claims(iss="https://evil.example.com"), rsa_private_key)
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_rejects_wrong_audience(self, rsa_private_key: str):
        token = _sign(_valid_claims(aud="api.evil.example.com"), rsa_private_key)
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_rejects_future_not_before(self, rsa_private_key: str):
        token = _sign(_valid_claims(nbf=int(datetime.now(UTC).timestamp()) + 3600), rsa_private_key)
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_rejects_missing_required_claims(self, rsa_private_key: str):
        token = _sign({"iss": settings.JWKS_ISSUER, "aud": settings.JWKS_AUDIENCE}, rsa_private_key)
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_rejects_expired_signed_token(self, rsa_private_key: str):
        token = _sign(_valid_claims(exp=int(datetime.now(UTC).timestamp()) - 3600), rsa_private_key)
        with pytest.raises(TokenExpiredError):
            verify_jwt(token)


# ---------------------------------------------------------------------------
# Startup key validation — verify_jwt_keys_usable
# ---------------------------------------------------------------------------
def _pem_private(key) -> str:
    """Serialize a private key object to PKCS8 PEM."""
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def _pem_public(key) -> str:
    """Serialize a public key object to SubjectPublicKeyInfo PEM."""
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


class TestVerifyJwtKeysUsable:
    """Startup validation: both keys must parse as RSA >= 2048 bits."""

    def test_valid_rsa_keys_pass(
        self, monkeypatch: pytest.MonkeyPatch, rsa_private_key: str, rsa_public_key: str
    ):
        monkeypatch.setattr(settings, "jwt_private_key", rsa_private_key)
        monkeypatch.setattr(settings, "jwt_public_key", rsa_public_key)
        verify_jwt_keys_usable()  # must not raise

    def test_garbage_private_key_rejected(
        self, monkeypatch: pytest.MonkeyPatch, rsa_public_key: str
    ):
        monkeypatch.setattr(settings, "jwt_private_key", "not a pem at all")
        monkeypatch.setattr(settings, "jwt_public_key", rsa_public_key)
        with pytest.raises(StartupError, match="private key"):
            verify_jwt_keys_usable()

    def test_garbage_public_key_rejected(
        self, monkeypatch: pytest.MonkeyPatch, rsa_private_key: str
    ):
        monkeypatch.setattr(settings, "jwt_private_key", rsa_private_key)
        monkeypatch.setattr(settings, "jwt_public_key", "not a pem at all")
        with pytest.raises(StartupError, match="public key"):
            verify_jwt_keys_usable()

    def test_small_rsa_private_key_rejected(self, monkeypatch: pytest.MonkeyPatch):
        small = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        monkeypatch.setattr(settings, "jwt_private_key", _pem_private(small))
        monkeypatch.setattr(settings, "jwt_public_key", _pem_public(small))
        with pytest.raises(StartupError, match="1024 bits"):
            verify_jwt_keys_usable()

    def test_small_rsa_public_key_rejected(self, monkeypatch: pytest.MonkeyPatch):
        full = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        monkeypatch.setattr(settings, "jwt_private_key", _pem_private(full))
        # valid private key + public key from a DIFFERENT (small) pair
        other_small = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        monkeypatch.setattr(settings, "jwt_public_key", _pem_public(other_small))
        with pytest.raises(StartupError, match="1024 bits"):
            verify_jwt_keys_usable()

    def test_non_rsa_private_key_rejected(self, monkeypatch: pytest.MonkeyPatch):
        ec_key = ec.generate_private_key(ec.SECP256R1())
        monkeypatch.setattr(settings, "jwt_private_key", _pem_private(ec_key))
        monkeypatch.setattr(settings, "jwt_public_key", _pem_public(ec_key))
        with pytest.raises(StartupError, match="not an RSA key"):
            verify_jwt_keys_usable()

    def test_non_rsa_public_key_rejected(
        self, monkeypatch: pytest.MonkeyPatch, rsa_private_key: str
    ):
        ec_key = ec.generate_private_key(ec.SECP256R1())
        monkeypatch.setattr(settings, "jwt_private_key", rsa_private_key)
        monkeypatch.setattr(settings, "jwt_public_key", _pem_public(ec_key))
        with pytest.raises(StartupError, match="not an RSA key"):
            verify_jwt_keys_usable()
