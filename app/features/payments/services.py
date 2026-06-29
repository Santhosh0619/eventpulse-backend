"""Business logic for Stripe payments: intents, webhooks, and refunds."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from stripe.error import SignatureVerificationError

from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.features.attendees import services as attendees_services
from app.features.events import services as events_services
from app.features.orders import crud as orders_crud
from app.features.organizations import services as orgs_services
from app.features.payments import crud, gateway
from app.features.payments.models import Payment
from app.features.payments.schemas import PaymentIntentResponse, RefundResponse
from app.features.tickets import services as tickets_services
from app.features.users import crud as users_crud
from app.features.users.models import User
from app.shared.enums import (
    NotificationType,
    OrderStatus,
    OrgMemberRole,
    PaymentStatus,
    UserRole,
)

ADMIN_ROLES = (OrgMemberRole.OWNER.value, OrgMemberRole.ADMIN.value)


async def create_payment_intent(
    db: AsyncSession, user: User, order_id: uuid.UUID
) -> PaymentIntentResponse:
    """Create a Stripe PaymentIntent for a pending order owned by the caller."""
    order = await orders_crud.get_order(db, order_id)
    if order is None:
        raise NotFoundError("Order not found")
    if order.user_id != user.id and user.role != UserRole.ADMIN.value:
        raise ForbiddenError("You do not have access to this order")
    if order.status != OrderStatus.PENDING.value:
        raise BadRequestError("This order is not awaiting payment")

    amount_minor = gateway.to_minor_units(order.total_amount, order.currency)
    intent = await gateway.create_payment_intent(
        amount_minor, order.currency, {"order_id": str(order.id)}
    )
    await crud.create_payment(
        db,
        order_id=order.id,
        stripe_payment_intent_id=intent["id"],
        amount=order.total_amount,
        currency=order.currency,
        status=PaymentStatus.PENDING.value,
    )
    return PaymentIntentResponse(
        client_secret=intent["client_secret"],
        payment_intent_id=intent["id"],
        amount=order.total_amount,
        currency=order.currency,
    )


async def _confirm_order_and_issue_tickets(db: AsyncSession, payment: Payment) -> None:
    """Confirm the paid order and generate its attendees (idempotent)."""
    order = await orders_crud.get_order(db, payment.order_id)
    if order is None or order.status != OrderStatus.PENDING.value:
        return
    order.status = OrderStatus.CONFIRMED.value
    order.confirmed_at = datetime.now(UTC)
    if order.user_id is not None:
        buyer = await users_crud.get_user_with_profile(db, order.user_id)
        if buyer is not None:
            await attendees_services.generate_attendees_for_order(db, order, buyer)

        from app.features.notifications import services as notifications_services

        # ``commit=False``: this notification must stay in the same transaction
        # as the order confirmation and ticket issuance, committed once below.
        await notifications_services.send_notification(
            db,
            user_id=order.user_id,
            type=NotificationType.ORDER_CONFIRMED.value,
            title="Order confirmed",
            message=f"Your order {order.order_number} has been confirmed.",
            data={"order_id": str(order.id), "screen": "order_detail"},
            commit=False,
        )


async def handle_webhook(
    db: AsyncSession, payload: bytes, sig_header: str | None
) -> None:
    """Verify and process a Stripe webhook event (idempotent)."""
    if not sig_header:
        raise BadRequestError("Missing Stripe signature")
    try:
        event = gateway.construct_event(payload, sig_header)
    except (ValueError, SignatureVerificationError) as exc:
        raise BadRequestError("Invalid webhook signature") from exc

    event_type = event["type"]
    data = event["data"]["object"]
    intent_id = data.get("id")
    if not intent_id:
        return

    # Lock the payment row so concurrent duplicate deliveries fulfill once.
    payment = await crud.lock_by_intent_id(db, intent_id)
    if payment is None:
        return  # Unknown intent; nothing to do.

    if event_type == "payment_intent.succeeded":
        if payment.status == PaymentStatus.SUCCEEDED.value:
            return  # Already processed.
        payment.status = PaymentStatus.SUCCEEDED.value
        methods = data.get("payment_method_types") or ["card"]
        payment.payment_method = methods[0]
        payment.payment_metadata = {"event_id": event.get("id")}
        await _confirm_order_and_issue_tickets(db, payment)
        await db.commit()
    elif event_type == "payment_intent.payment_failed":
        payment.status = PaymentStatus.FAILED.value
        await db.commit()


async def process_refund(
    db: AsyncSession,
    user: User,
    order_id: uuid.UUID,
    amount: Decimal | None,
    reason: str | None,
) -> RefundResponse:
    """Refund (all or part of) an order's payment (org admin or owner)."""
    order = await orders_crud.get_order(db, order_id)
    if order is None:
        raise NotFoundError("Order not found")
    if order.event_id is None:
        raise BadRequestError("Order is not linked to an event")

    event = await events_services.get_event(db, order.event_id)
    role = await orgs_services.get_user_org_role(db, event.organization_id, user.id)
    if role is None or role not in ADMIN_ROLES:
        raise ForbiddenError("Requires organization admin or owner role")

    payment = await crud.get_latest_for_order(db, order_id)
    if payment is None or payment.status not in (
        PaymentStatus.SUCCEEDED.value,
        PaymentStatus.PARTIALLY_REFUNDED.value,
    ):
        raise BadRequestError("No completed payment to refund")

    remaining = payment.amount - payment.refund_amount
    refund_amount = amount if amount is not None else remaining
    if refund_amount <= 0 or refund_amount > remaining:
        raise BadRequestError("Invalid refund amount")

    amount_minor = gateway.to_minor_units(refund_amount, payment.currency)
    await gateway.create_refund(payment.stripe_payment_intent_id, amount_minor)

    payment.refund_amount = payment.refund_amount + refund_amount
    if reason is not None:
        payment.refund_reason = reason

    fully_refunded = payment.refund_amount >= payment.amount
    payment.status = (
        PaymentStatus.REFUNDED.value
        if fully_refunded
        else PaymentStatus.PARTIALLY_REFUNDED.value
    )

    # Only a full refund cancels the order and releases its reserved inventory;
    # a partial refund leaves the order confirmed and the tickets held.
    if fully_refunded:
        order.status = OrderStatus.REFUNDED.value
        for item in order.items:
            if item.ticket_type_id is not None:
                await tickets_services.release(db, item.ticket_type_id, item.quantity)

    await db.commit()
    await db.refresh(payment)
    return RefundResponse(
        order_id=order.id,
        refunded_amount=payment.refund_amount,
        payment_status=payment.status,
        order_status=order.status,
    )
