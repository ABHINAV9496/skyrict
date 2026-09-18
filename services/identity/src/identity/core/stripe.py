"""Stripe client wrapper - the single boundary to the Stripe SDK.

The webhook endpoint verifies event signatures here and hands a constructed
``Event`` to the billing service; the service never imports ``stripe``
directly. Everything is env-driven via ``settings``; empty keys (dev/test)
disable Stripe entirely.

``webhook_secret`` is injectable for testability: signature verification is
purely local (HMAC over the raw payload), so tests can construct a signed
payload with a throwaway ``whsec_...`` secret without network access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from identity.core.config import settings

if TYPE_CHECKING:
    from stripe import Event


class StripeError(Exception):
    """Base class for Stripe boundary failures."""


class InvalidSignatureError(StripeError):
    """The webhook payload could not be authenticated."""


class StripeClient:
    """Env-driven thin wrapper over the Stripe SDK."""

    def __init__(
        self,
        *,
        secret_key: str | None = None,
        webhook_secret: str | None = None,
    ) -> None:
        self._secret_key = (
            secret_key if secret_key is not None else settings.BILLING_STRIPE_SECRET_KEY
        )
        self._webhook_secret = (
            webhook_secret if webhook_secret is not None else settings.BILLING_STRIPE_WEBHOOK_SECRET
        )

    @property
    def enabled(self) -> bool:
        """True when both keys are configured (Stripe calls are usable)."""
        return bool(self._secret_key and self._webhook_secret)

    def construct_event(self, payload: bytes, signature_header: str) -> Event:
        """Verify the webhook signature and return the parsed Stripe Event.

        Raises:
            InvalidSignatureError: the signature does not match (replay,
                tampered payload, or a wrong webhook secret).
        """
        if not self._webhook_secret:
            raise InvalidSignatureError(
                "Stripe webhook secret is not configured - refusing unverified events"
            )
        try:
            import stripe
        except ImportError as exc:  # pragma: no cover - dep declared in pyproject
            raise StripeError("Stripe SDK is not installed") from exc

        try:
            return stripe.Webhook.construct_event(
                payload=payload,
                sig_header=signature_header,
                secret=self._webhook_secret,
            )
        except stripe.error.SignatureVerificationError as exc:
            raise InvalidSignatureError(str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise StripeError(f"Could not construct Stripe event: {exc}") from exc
