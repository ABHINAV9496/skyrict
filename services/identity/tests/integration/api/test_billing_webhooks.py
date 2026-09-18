"""Integration tests for the Stripe webhook endpoint (BILLING-SERV-002).

Cover the HTTP contract:
  * an unsigned / badly-signed payload is rejected with 401 (JSON problem),
  * a validly-signed unknown event is acknowledged (200, ``ignored``) and the
    idempotency store records it, so Stripe stops retrying,
  * the endpoint never requires a bearer token (signature is the auth).

Signature verification is local HMAC - the helper builds a real Stripe-format
``t=...,v1=...`` header with a throwaway ``whsec_...`` secret, so no Stripe
network access is needed.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from typing import TYPE_CHECKING

import pytest

from identity.core.stripe import StripeClient
from identity.main import app

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration

_WH_SECRET = "whsec_test_secret_1234567890abcdef"


def _stripe_signature(payload: bytes, *, secret: str = _WH_SECRET) -> str:
    """Build a Stripe-format signature header for the raw body."""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}." + payload.decode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256)
    return f"t={timestamp},v1={digest.hexdigest()}"


def _event_payload(event_id: str, event_type: str, *, customer: str = "cus_123") -> bytes:
    import json

    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "data": {"object": {"id": "sub_789", "customer": customer, "status": "active"}},
        }
    ).encode("utf-8")


class TestWebhookSignatureRejection:
    async def test_missing_signature_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/billing/webhooks", content=_event_payload("evt_1", "invoice.payment_succeeded")
        )

        assert resp.status_code == 401
        assert resp.json()["type"].endswith("/authentication-error")

    async def test_forged_signature_returns_401(self, client: AsyncClient) -> None:
        payload = _event_payload("evt_2", "invoice.payment_succeeded")
        forged = _stripe_signature(payload, secret="whsec_wrong_secret")

        resp = await client.post(
            "/api/v1/billing/webhooks",
            content=payload,
            headers={"stripe-signature": forged},
        )

        assert resp.status_code == 401
        assert resp.json()["type"].endswith("/authentication-error")


class TestWebhookDelivery:
    async def test_valid_unknown_event_acknowledged_and_recorded(
        self, client: AsyncClient
    ) -> None:
        from identity.api.deps import get_stripe_client

        app.dependency_overrides[get_stripe_client] = lambda: StripeClient(
            webhook_secret=_WH_SECRET
        )
        file_tail = uuid.uuid4().hex[:12]
        event_id = f"evt_integration_{file_tail}"
        try:
            resp = await client.post(
                "/api/v1/billing/webhooks",
                content=_event_payload(event_id, "invoice.payment_succeeded"),
                headers={"stripe-signature": _stripe_signature(_event_payload(event_id, "invoice.payment_succeeded"))},
            )

            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["status"] == "ignored"

            from sqlalchemy import text

            from identity.db.session import async_session_factory

            async with async_session_factory() as session:
                row = await session.execute(
                    text("SELECT id FROM processed_stripe_events WHERE event_id = :eid"),
                    {"eid": event_id},
                )
                assert row.scalar_one_or_none() is not None
        finally:
            app.dependency_overrides.pop(get_stripe_client, None)
