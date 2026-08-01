"""JWT sign/verify (RS256) and password hashing (Argon2id).

Every other layer MUST go through these functions. Never verify JWTs inline.
Single verification path: verify_jwt().
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict, cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from jose import JWTError, jwt

from identity.core.config import settings
from identity.core.exceptions import TokenExpiredError, TokenInvalidError

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
