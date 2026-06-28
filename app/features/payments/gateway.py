"""Thin async wrappers around the Stripe SDK.

Isolated here so the rest of the code depends on small functions that are easy
to mock in tests (no network calls during testing).
"""

import asyncio
from typing import Any

import stripe

from app.core.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY


def to_minor_units(amount: float, currency: str) -> int:
    """Convert a major-unit amount (e.g. 10.50) to Stripe minor units (1050)."""
    # Zero-decimal currencies are rare here; INR/USD both use 2 decimals.
    return int(round(float(amount) * 100))


async def create_payment_intent(
    amount_minor: int, currency: str, metadata: dict[str, str]
) -> Any:
    """Create a Stripe PaymentIntent and return it."""
    return await asyncio.to_thread(
        stripe.PaymentIntent.create,
        amount=amount_minor,
        currency=currency.lower(),
        metadata=metadata,
        automatic_payment_methods={"enabled": True},
    )


async def create_refund(payment_intent_id: str, amount_minor: int) -> Any:
    """Create a Stripe refund for (part of) a PaymentIntent."""
    return await asyncio.to_thread(
        stripe.Refund.create,
        payment_intent=payment_intent_id,
        amount=amount_minor,
    )


def construct_event(payload: bytes, sig_header: str) -> Any:
    """Verify a webhook signature and return the parsed Stripe event.

    Raises ValueError or stripe.error.SignatureVerificationError on failure.
    """
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )
