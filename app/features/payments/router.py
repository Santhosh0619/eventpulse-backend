"""Payment endpoints: create intent, Stripe webhook, and refunds."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import DBSession, get_current_user
from app.features.payments import services
from app.features.payments.schemas import (
    CreateIntentRequest,
    PaymentIntentResponse,
    RefundRequest,
    RefundResponse,
    WebhookResponse,
)
from app.features.users.models import User

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "/payments/create-intent",
    response_model=PaymentIntentResponse,
    summary="Create a payment intent",
)
async def create_intent(
    payload: CreateIntentRequest, current_user: CurrentUser, db: DBSession
) -> PaymentIntentResponse:
    """Create a Stripe PaymentIntent for a pending order (authenticated owner)."""
    return await services.create_payment_intent(db, current_user, payload.order_id)


@router.post(
    "/webhooks/stripe",
    response_model=WebhookResponse,
    summary="Stripe webhook receiver",
)
async def stripe_webhook(request: Request, db: DBSession) -> WebhookResponse:
    """Receive and process Stripe webhook events (signature-verified, no auth)."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    await services.handle_webhook(db, payload, sig_header)
    return WebhookResponse(received=True)


@router.post(
    "/orders/{order_id}/refund",
    response_model=RefundResponse,
    summary="Refund an order",
)
async def refund_order(
    order_id: uuid.UUID,
    payload: RefundRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> RefundResponse:
    """Refund all or part of an order's payment (org admin or owner)."""
    return await services.process_refund(
        db, current_user, order_id, payload.amount, payload.reason
    )
