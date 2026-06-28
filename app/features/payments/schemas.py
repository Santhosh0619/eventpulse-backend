"""Pydantic schemas for the payments feature."""

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field


class CreateIntentRequest(BaseModel):
    """Payload for creating a Stripe PaymentIntent for an order."""

    order_id: uuid.UUID


class PaymentIntentResponse(BaseModel):
    """Client secret and metadata returned for front-end payment confirmation."""

    client_secret: str
    payment_intent_id: str
    amount: Decimal
    currency: str


class RefundRequest(BaseModel):
    """Payload for refunding an order (optional partial amount + reason)."""

    amount: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    reason: str | None = None


class RefundResponse(BaseModel):
    """Result of a refund operation."""

    order_id: uuid.UUID
    refunded_amount: Decimal
    payment_status: str
    order_status: str


class WebhookResponse(BaseModel):
    """Acknowledgement returned to Stripe for a processed webhook."""

    received: bool = True
