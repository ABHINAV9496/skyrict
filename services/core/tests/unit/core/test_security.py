"""verify_jwt tests — RS256, algorithm whitelist, issuer/audience, expiry."""

from __future__ import annotations

import time
import uuid

import pytest
from jose import jwt

from core.core.config import settings
from core.core.security import cross_check_jwt_tenant, verify_jwt
from skyrict_common.exceptions import TenantMismatchError, TokenExpiredError, TokenInvalidError

_TENANT = str(uuid.uuid4())
_SUB = str(uuid.uuid4())


def _token(
    private_key: str,
    *,
    issuer: str | None = None,
    audience: str | None = None,
    exp: int | None = None,
    nbf: int | None = None,
    tenant_id: str | None = None,
    type_: str = "access",
) -> str:
    now = int(time.time())
    payload: dict = {
        "sub": _SUB,
        "tenant_id": tenant_id or _TENANT,
        "iss": issuer if issuer is not None else "https://auth.test.skyrict.io",
        "aud": audience if audience is not None else "api.test.skyrict.io",
        "iat": now,
        "nbf": nbf if nbf is not None else now - 10,
        "exp": exp if exp is not None else now + 300,
        "type": type_,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture(autouse=True)
def _configure_verifier(rsa_public_key: str) -> None:
    """Point the module settings at the ephemeral session keypair."""
    settings.jwt_public_key = rsa_public_key
    settings.JWKS_ISSUER = "https://auth.test.skyrict.io"
    settings.JWKS_AUDIENCE = "api.test.skyrict.io"


class TestVerifyJwt:
    def test_valid_token(self, rsa_private_key: str) -> None:
        claims = verify_jwt(_token(rsa_private_key))
        assert claims["sub"] == _SUB
        assert claims["tenant_id"] == _TENANT
        assert claims["type"] == "access"

    def test_expired_token_rejected(self, rsa_private_key: str) -> None:
        token = _token(rsa_private_key, exp=int(time.time()) - 60)
        with pytest.raises(TokenExpiredError):
            verify_jwt(token)

    def test_not_yet_valid_rejected(self, rsa_private_key: str) -> None:
        token = _token(rsa_private_key, nbf=int(time.time()) + 600)
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_wrong_issuer_rejected(self, rsa_private_key: str) -> None:
        token = _token(rsa_private_key, issuer="https://evil.example")
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_wrong_audience_rejected(self, rsa_private_key: str) -> None:
        token = _token(rsa_private_key, audience="other-audience")
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_hmac_algorithm_rejected(self) -> None:
        # Algorithm-confusion attempt: HMAC-signed with a plain shared secret.
        # python-jose refuses to use an asymmetric PEM as an HMAC secret, so a
        # raw secret string is the realistic confusion vector; verify_jwt must
        # reject it at the header whitelist before any key is consulted.
        now = int(time.time())
        payload = {
            "sub": _SUB,
            "tenant_id": _TENANT,
            "iss": "https://auth.test.skyrict.io",
            "aud": "api.test.skyrict.io",
            "iat": now,
            "nbf": now - 10,
            "exp": now + 300,
            "type": "access",
        }
        token = jwt.encode(payload, "compromised-shared-secret", algorithm="HS256")
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_garbage_rejected(self) -> None:
        with pytest.raises(TokenInvalidError):
            verify_jwt("not-a-jwt")

    def test_none_algorithm_rejected(self) -> None:
        token = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhIn0."
        with pytest.raises(TokenInvalidError):
            verify_jwt(token)


class TestCrossCheckTenant:
    def test_matching_tenant_passes(self) -> None:
        cross_check_jwt_tenant(_TENANT, _TENANT)

    def test_mismatch_raises(self) -> None:
        with pytest.raises(TenantMismatchError):
            cross_check_jwt_tenant(_TENANT, str(uuid.uuid4()))
