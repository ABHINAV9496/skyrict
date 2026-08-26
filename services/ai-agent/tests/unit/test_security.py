"""Unit tests for JWT verification (the single decode path)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from jose import jwt as jose_jwt

from ai_agent.core.exceptions import TokenExpiredError, TokenInvalidError
from ai_agent.core.security import cross_check_jwt_tenant, verify_jwt
from skyrict_common.exceptions import TenantMismatchError


def _b64url(data: bytes) -> str:
    """Base64url-encode without padding (JWT segment encoding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_token(
    private_key: str,
    *,
    sub: str = "11111111-1111-1111-1111-111111111111",
    tenant_id: str = "22222222-2222-2222-2222-222222222222",
    expires_in: int = 300,
    algorithm: str = "RS256",
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "tenant_id": tenant_id,
        "iss": "https://auth.test.skyrict.io",
        "aud": "api.test.skyrict.io",
        "iat": now,
        "nbf": now,
        "exp": now + expires_in,
        "type": "access",
    }
    return jose_jwt.encode(payload, private_key, algorithm=algorithm)


def _make_hmac_confused_token(public_key_pem: str) -> str:
    """Forge a token with header alg=HS512, HMAC-signed with the RSA PUBLIC
    key PEM as the shared secret — the classic RS256->HS512 algorithm
    confusion payload.

    python-jose refuses to construct this itself (an asymmetric key cannot be
    an HMAC secret), so the token is assembled by hand. verify_jwt() must
    reject it on the algorithm whitelist before any signature work.
    """
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "HS512", "typ": "JWT"}).encode())
    payload = _b64url(
        json.dumps(
            {
                "sub": "11111111-1111-1111-1111-111111111111",
                "tenant_id": "22222222-2222-2222-2222-222222222222",
                "iss": "https://auth.test.skyrict.io",
                "aud": "api.test.skyrict.io",
                "iat": now,
                "nbf": now,
                "exp": now + 300,
                "type": "access",
            }
        ).encode()
    )
    signing_input = f"{header}.{payload}"
    signature = _b64url(
        hmac.new(
            public_key_pem.encode(),
            signing_input.encode(),
            digestmod=hashlib.sha512,
        ).digest()
    )
    return f"{signing_input}.{signature}"


class TestVerifyJwt:
    def test_valid_token_round_trips(self, rsa_private_key: str) -> None:
        token = _make_token(rsa_private_key)

        claims = verify_jwt(token)

        assert claims["sub"] == "11111111-1111-1111-1111-111111111111"
        assert claims["type"] == "access"

    def test_expired_token_rejected(self, rsa_private_key: str) -> None:
        token = _make_token(rsa_private_key, expires_in=-10)

        with pytest.raises(TokenExpiredError):
            verify_jwt(token)

    def test_garbage_token_rejected(self) -> None:
        with pytest.raises(TokenInvalidError):
            verify_jwt("not-a-token")

    def test_algorithm_confusion_rejected(self, rsa_public_key: str) -> None:
        token = _make_hmac_confused_token(rsa_public_key)

        with pytest.raises(TokenInvalidError):
            verify_jwt(token)

    def test_wrong_audience_rejected(self, rsa_private_key: str) -> None:
        now = int(time.time())
        token = jose_jwt.encode(
            {
                "sub": "sub",
                "tenant_id": "t",
                "iss": "https://auth.test.skyrict.io",
                "aud": "wrong-audience",
                "iat": now,
                "nbf": now,
                "exp": now + 300,
            },
            rsa_private_key,
            algorithm="RS256",
        )

        with pytest.raises(TokenInvalidError):
            verify_jwt(token)


class TestCrossCheckJwtTenant:
    def test_matching_tenant_passes(self) -> None:
        tenant = "22222222-2222-2222-2222-222222222222"
        cross_check_jwt_tenant(tenant, tenant)

    def test_mismatched_tenant_raises(self) -> None:
        with pytest.raises(TenantMismatchError):
            cross_check_jwt_tenant("a", "b")
