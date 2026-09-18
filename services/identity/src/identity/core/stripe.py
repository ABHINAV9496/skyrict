"""Stripe client wrapper - the single boundary to the Stripe SDK.

The webhook endpoint verifies event signatures here and hands a constructed
``Event`` to the billing service; the service never imports ``stripe``
directly. Everything is env-driven via ``settings``; empty keys (dev/test)
disable Stripe entirely.

``webhook_secret`` is injectable for testability: signature verification is
purely local (HMAC over the raw payload), so tests can construct a signed
payload with a throwaway ``whsec_...`` secret without network access.

Checkout/portal session creation follows the same boundary: callers get
plain dicts (``{"id": ..., "url": ...}``), never SDK objects, so the rest
of the codebase is insulated from the untyped ``stripe`` module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from identity.core.config import settings

if TYPE_CHECKING:
    from stripe import Event


class StripeError(Exception):
    """Base class for Stripe boundary failures."""


class InvalidSignatureError(StripeError):
    """The webhook payload could not be authenticated."""


class StripeDisabledError(StripeError):
    """Stripe is not configured (missing keys) - operations are unavailable."""


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

    def _require_enabled(self) -> None:
        """Refuse Stripe calls when keys are missing.

        Raises:
            StripeDisabledError: Stripe is not configured - the API layer
                maps this to a sanitized 503 (ServiceUnavailableError).
        """
        if not self.enabled:
            raise StripeDisabledError(
                "Stripe is not configured - set BILLING_STRIPE_SECRET_KEY and "
                "BILLING_STRIPE_WEBHOOK_SECRET to enable billing operations"
            )

    @staticmethod
    def _import_stripe() -> Any:
        """Import the Stripe SDK lazily (declared dependency, dev/test safe)."""
        try:
            import stripe
        except ImportError as exc:  # pragma: no cover - dep declared in pyproject
            raise StripeError("Stripe SDK is not installed") from exc
        return stripe

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
        stripe = self._import_stripe()
        try:
            # The SDK module is untyped (Any); pin the strict return type.
            return cast(
                "Event",
                stripe.Webhook.construct_event(
                    payload=payload,
                    sig_header=signature_header,
                    secret=self._webhook_secret,
                ),
            )
        except stripe.error.SignatureVerificationError as exc:
            raise InvalidSignatureError(str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise StripeError(f"Could not construct Stripe event: {exc}") from exc

    def create_customer(
        self,
        *,
        email: str | None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a Stripe Customer and return ``{"id": ...}``.

        The customer is created lazily on first checkout so a tenant has a
        billing identity to reference in later sessions and webhooks.
        """
        self._require_enabled()
        stripe = self._import_stripe()
        try:
            customer = stripe.Customer.create(email=email, metadata=metadata or {})
        except stripe.error.StripeError as exc:
            raise StripeError(f"Could not create Stripe customer: {exc}") from exc
        return {"id": customer.id}

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        client_reference_id: str,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a Stripe Checkout Session and return ``{"id", "url"}``.

        The subscription-mode session redirects the browser to ``url``; the
        webhook handler matches the completing session back to the tenant via
        ``client_reference_id`` (the tenant id).
        """
        self._require_enabled()
        stripe = self._import_stripe()
        try:
            session = stripe.checkout.Session.create(
                mode="subscription",
                customer=customer_id,
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=client_reference_id,
                metadata=metadata or {},
                billing_address_collection="auto",
            )
        except stripe.error.StripeError as exc:
            raise StripeError(f"Could not create checkout session: {exc}") from exc
        return {"id": session.id, "url": session.url}

    def create_portal_session(self, *, customer_id: str, return_url: str) -> dict[str, Any]:
        """Create a Stripe Customer Portal Session and return ``{"id", "url"}``."""
        self._require_enabled()
        stripe = self._import_stripe()
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
        except stripe.error.StripeError as exc:
            raise StripeError(f"Could not create portal session: {exc}") from exc
        return {"id": session.id, "url": session.url}
