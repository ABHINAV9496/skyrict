"""JWT sign/verify (RS256) and password hashing (Argon2id).

Every other layer MUST go through these functions. Never verify JWTs inline.
Single verification path: verify_jwt().
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import JWTError, jwt

from identity.core.config import settings
from identity.core.exceptions import StartupError, TokenExpiredError, TokenInvalidError

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.types import (
        PrivateKeyTypes,
        PublicKeyTypes,
    )

# Algorithms we accept — explicitly whitelisted. Rejects "none" and any
# header-driven algorithm switching (CVE-2015-2951 / algorithm confusion).
_ALLOWED_ALGORITHMS = {"RS256"}


class TokenClaims(TypedDict):
    """Verified JWT claims returned by :func:`verify_jwt`.

    ``iat``/``nbf``/``exp`` are POSIX timestamps (epoch seconds).
    ``type`` is ``"access"`` or ``"refresh"``.
    """

    sub: str
    tenant_id: str
    iss: str
    aud: str
    iat: int
    exp: int
    nbf: int
    type: str
    session_id: NotRequired[str]


# ---------------------------------------------------------------------------
# Password hashing — Argon2id (OWASP recommended)
#
# argon2-cffi is a hard dependency (see pyproject.toml). If it is missing the
# import fails at startup — there is deliberately NO fallback that silently
# weakens hashing (e.g. plaintext comparison).
# ---------------------------------------------------------------------------
_ph = PasswordHasher(
    time_cost=3,  # number of iterations
    memory_cost=65536,  # 64 MB
    parallelism=4,  # threads
    hash_len=32,  # output length
    salt_len=16,  # salt length
)


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id.

    Uses a random salt per call — hashes for the same password always differ.
    """
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its Argon2id hash.

    Returns False (never raises) for wrong passwords and malformed hashes so
    callers don't need to know about Argon2 exception types.
    """
    try:
        return _ph.verify(hashed_password, plain_password)
    except (InvalidHashError, VerificationError):
        return False


# ---------------------------------------------------------------------------
# JWT — RS256 only
# ---------------------------------------------------------------------------
def create_access_token(
    subject: str,
    *,
    tenant_id: str,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed RS256 access token.

    Args:
        subject: User ID (sub claim).
        tenant_id: Tenant ID (tenant_id claim) — always included.
        extra_claims: Additional claims to embed.
        expires_delta: Override default expiry.
    """
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload: dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "iss": settings.JWKS_ISSUER,
        "aud": settings.JWKS_AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": expire,
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_private_key, algorithm="RS256")


def create_refresh_token(
    subject: str,
    *,
    tenant_id: str,
    session_id: str | None = None,
) -> str:
    """Create a signed RS256 refresh token with longer expiry."""
    now = datetime.now(UTC)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "iss": settings.JWKS_ISSUER,
        "aud": settings.JWKS_AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": expire,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
    }
    if session_id is not None:
        payload["session_id"] = session_id
    return jwt.encode(payload, settings.jwt_private_key, algorithm="RS256")


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_email_verification_token(subject: str, *, tenant_id: str) -> str:
    """Create a short-lived RS256 token proving intent to verify an email.

    Carries ``type="email_verify"`` so consumers can reject tokens minted for
    other purposes. Verified via :func:`verify_jwt` (the ONE decode path).
    """
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.VERIFICATION_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "iss": settings.JWKS_ISSUER,
        "aud": settings.JWKS_AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": expire,
        "type": "email_verify",
    }
    return jwt.encode(payload, settings.jwt_private_key, algorithm="RS256")


def verify_jwt(token: str) -> TokenClaims:
    """Decode and VERIFY a JWT — the ONE AND ONLY verification path.

    Security guarantees:
      - RS256 only (asymmetric — public key verifies, private key signs)
      - Algorithm whitelist rejects "none" and header-driven attacks
      - Issuer and audience are validated
      - Expiry (exp) and not-before (nbf) are checked

    Returns:
        The verified claims as a :class:`TokenClaims`.

    Raises:
        TokenExpiredError: If the token has expired.
        TokenInvalidError: If the token is malformed, signature is invalid,
            algorithm is not RS256, or issuer/audience don't match.
    """
    try:
        # First: check the header's alg BEFORE jose decodes anything.
        # This catches algorithm confusion attacks at the earliest point.
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg", "")
        if alg not in _ALLOWED_ALGORITHMS:
            raise TokenInvalidError(f"Token algorithm '{alg}' is not allowed. Expected RS256.")

        # Decode with public key, explicit algorithm whitelist, and claim validation
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=list(_ALLOWED_ALGORITHMS),
            issuer=settings.JWKS_ISSUER,
            audience=settings.JWKS_AUDIENCE,
            options={
                # python-jose uses one require_* flag per claim (not a "require"
                # list). Enforce every claim our contract needs so tokens that
                # omit exp/iat/sub/iss/aud are rejected, not silently accepted.
                "require_aud": True,
                "require_iat": True,
                "require_exp": True,
                "require_iss": True,
                "require_sub": True,
            },
        )
        return cast("TokenClaims", payload)

    except JWTError as exc:
        exc_str = str(exc).lower()
        if "expired" in exc_str:
            raise TokenExpiredError() from exc
        raise TokenInvalidError(str(exc)) from exc


# ---------------------------------------------------------------------------
# JWT key material — startup validation
# ---------------------------------------------------------------------------
def _verify_rsa_key_size(key: rsa.RSAPrivateKey | rsa.RSAPublicKey, label: str) -> None:
    """Reject RSA keys below 2048 bits (NIST / PCI-DSS baseline)."""
    if key.key_size < 2048:
        raise StartupError(
            f"JWT {label} key is only {key.key_size} bits — RSA 2048 or larger required"
        )


def verify_jwt_keys_usable() -> None:
    """Verify both configured JWT keys parse as RSA keys of >= 2048 bits.

    Runs ONCE at application startup so a corrupt, non-RSA, or weak key fails
    fast at boot (the lifespan raises :class:`StartupError`) instead of
    surfacing mid-request as opaque signing/verification failures.

    Raises:
        StartupError: If either key cannot be parsed, is not RSA, or is
            smaller than 2048 bits.
    """
    try:
        private_key: PrivateKeyTypes = serialization.load_pem_private_key(
            settings.jwt_private_key.encode("utf-8"),
            password=None,
        )
    except (TypeError, UnsupportedAlgorithm, ValueError) as exc:
        raise StartupError(f"JWT private key is not a valid PEM private key: {exc}") from exc

    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise StartupError(f"JWT private key is not an RSA key (got {type(private_key).__name__})")
    _verify_rsa_key_size(private_key, "private")

    try:
        public_key: PublicKeyTypes = serialization.load_pem_public_key(
            settings.jwt_public_key.encode("utf-8"),
        )
    except (TypeError, UnsupportedAlgorithm, ValueError) as exc:
        raise StartupError(f"JWT public key is not a valid PEM public key: {exc}") from exc

    if not isinstance(public_key, rsa.RSAPublicKey):
        raise StartupError(f"JWT public key is not an RSA key (got {type(public_key).__name__})")
    _verify_rsa_key_size(public_key, "public")
