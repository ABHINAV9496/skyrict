from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import JWTError, jwt

from identity.core.config import settings
from identity.core.exceptions import StartupError, TokenExpiredError, TokenInvalidError
from identity.domain.value_objects import PasswordPolicy
from skyrict_common.exceptions import ValidationError

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.types import (
        PrivateKeyTypes,
        PublicKeyTypes,
    )


_ALLOWED_ALGORITHMS = {"RS256"}


class TokenClaims(TypedDict):
    sub: str
    tenant_id: str
    iss: str
    aud: str
    iat: int
    exp: int
    nbf: int
    type: str
    session_id: NotRequired[str]


_ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return _ph.verify(hashed_password, plain_password)
    except (InvalidHashError, VerificationError):
        return False


def validate_password_policy(password: str) -> None:
    errors = PasswordPolicy(
        min_length=settings.PASSWORD_MIN_LENGTH,
        require_uppercase=settings.PASSWORD_REQUIRE_UPPERCASE,
        require_lowercase=settings.PASSWORD_REQUIRE_LOWERCASE,
        require_digit=settings.PASSWORD_REQUIRE_DIGIT,
        require_special=settings.PASSWORD_REQUIRE_SPECIAL,
    ).validate(password)
    if errors:
        raise ValidationError("; ".join(errors))


def encrypt_mfa_secret(secret: str) -> str:
    return (
        Fernet(settings.MFA_ENCRYPTION_KEY.encode("utf-8"))
        .encrypt(secret.encode("utf-8"))
        .decode("utf-8")
    )


def decrypt_mfa_secret(encrypted_secret: str) -> str:
    return (
        Fernet(settings.MFA_ENCRYPTION_KEY.encode("utf-8"))
        .decrypt(encrypted_secret.encode("utf-8"))
        .decode("utf-8")
    )


def mfa_is_required(
    *,
    roles: list[str],
    mfa_enabled: bool,
    tenant_requires_all_members: bool,
) -> bool:

    if mfa_enabled:
        return False
    return "tenant_owner" in roles or tenant_requires_all_members


def create_access_token(
    subject: str,
    *,
    tenant_id: str,
    extra_claims: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:

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


def hash_invitation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_jwt(token: str) -> TokenClaims:
    try:
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg", "")
        if alg not in _ALLOWED_ALGORITHMS:
            raise TokenInvalidError(f"Token algorithm '{alg}' is not allowed. Expected RS256.")

        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=list(_ALLOWED_ALGORITHMS),
            issuer=settings.JWKS_ISSUER,
            audience=settings.JWKS_AUDIENCE,
            options={
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


def _verify_rsa_key_size(key: rsa.RSAPrivateKey | rsa.RSAPublicKey, label: str) -> None:
    if key.key_size < 2048:
        raise StartupError(
            f"JWT {label} key is only {key.key_size} bits — RSA 2048 or larger required"
        )


def verify_jwt_keys_usable() -> None:
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


def verify_mfa_encryption_key() -> None:
    try:
        Fernet(settings.MFA_ENCRYPTION_KEY.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise StartupError("MFA_ENCRYPTION_KEY is not a valid Fernet key") from exc
