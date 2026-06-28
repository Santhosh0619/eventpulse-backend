"""Business logic for the order pipeline."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.features.events import services as events_services
from app.features.orders import crud
from app.features.orders.models import Order, OrderItem
from app.features.tickets import services as tickets_services
from app.features.users.models import User
from app.shared.enums import EventStatus, OrderStatus, UserRole

# Pending orders expire after this window (used in Phase 6's payment flow).
ORDER_EXPIRY = timedelta(minutes=15)


async def generate_order_number(db: AsyncSession) -> str:
    """Generate a unique human-readable order number (EP-YYYYMMDD-XXXX)."""
    date_part = datetime.now(UTC).strftime("%Y%m%d")
    for _ in range(10):
        candidate = f"EP-{date_part}-{secrets.token_hex(2).upper()}"
        if not await crud.order_number_exists(db, candidate):
            return candidate
    raise BadRequestError("Could not generate a unique order number")


async def place_order(db: AsyncSession, user: User, payload: dict) -> Order:
    """Place an order: validate, atomically reserve inventory, and (mock) confirm.

    All steps run in a single transaction. Ticket inventory is reserved with
    row locks so concurrent orders cannot oversell. Payment is mocked in Phase 5,
    so the order is confirmed immediately; Phase 6 will gate confirmation on a
    Stripe webhook.
    """
    event = await events_services.get_event(db, payload["event_id"])  # 404
    if event.status != EventStatus.PUBLISHED.value:
        raise BadRequestError("This event is not open for orders")

    now = datetime.now(UTC)
    total = Decimal("0")
    currency: str | None = None
    order_items: list[OrderItem] = []

    for item in payload["items"]:
        type_id = item["ticket_type_id"]
        quantity = item["quantity"]
        # Lock + reserve inventory; returns the locked tier (or raises).
        tier = await tickets_services.atomic_reserve(db, type_id, quantity)
        if tier.event_id != event.id:
            raise BadRequestError("A ticket type does not belong to this event")
        if quantity > tier.max_per_order:
            raise BadRequestError(
                f"At most {tier.max_per_order} tickets of '{tier.name}' per order"
            )
        if currency is None:
            currency = tier.currency
        elif tier.currency != currency:
            raise BadRequestError("All items in an order must use the same currency")
        subtotal = tier.price * quantity
        total += subtotal
        order_items.append(
            OrderItem(
                ticket_type_id=tier.id,
                quantity=quantity,
                unit_price=tier.price,
                subtotal=subtotal,
            )
        )

    order = Order(
        order_number=await generate_order_number(db),
        user_id=user.id,
        event_id=event.id,
        status=OrderStatus.CONFIRMED.value,  # mock payment auto-confirms (Phase 5)
        total_amount=total,
        currency=currency or "INR",
        notes=payload.get("notes"),
        confirmed_at=now,
        items=order_items,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


async def get_order(db: AsyncSession, order_id: uuid.UUID, user: User) -> Order:
    """Return an order the caller owns (admins may view any order)."""
    order = await crud.get_order(db, order_id)
    if order is None:
        raise NotFoundError("Order not found")
    if order.user_id != user.id and user.role != UserRole.ADMIN.value:
        raise ForbiddenError("You do not have access to this order")
    return order


async def list_my_orders(db: AsyncSession, user: User) -> list[Order]:
    """Return the authenticated user's orders."""
    return await crud.list_user_orders(db, user.id)


async def cancel_order(db: AsyncSession, order_id: uuid.UUID, user: User) -> Order:
    """Cancel an order the caller owns, releasing reserved inventory."""
    order = await crud.get_order(db, order_id)
    if order is None:
        raise NotFoundError("Order not found")
    if order.user_id != user.id and user.role != UserRole.ADMIN.value:
        raise ForbiddenError("You do not have access to this order")
    if order.status not in (
        OrderStatus.PENDING.value,
        OrderStatus.CONFIRMED.value,
    ):
        raise BadRequestError(f"Cannot cancel an order that is {order.status}")

    for item in order.items:
        if item.ticket_type_id is not None:
            await tickets_services.release(db, item.ticket_type_id, item.quantity)

    order.status = OrderStatus.CANCELLED.value
    order.cancelled_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(order)
    return order


async def cleanup_expired_orders(db: AsyncSession) -> int:
    """Cancel expired pending orders and release their inventory.

    Returns the number of orders expired. Invoked periodically by the scheduler.
    """
    now = datetime.now(UTC)
    expired = await crud.get_expired_pending(db, now)
    for order in expired:
        for item in order.items:
            if item.ticket_type_id is not None:
                await tickets_services.release(db, item.ticket_type_id, item.quantity)
        order.status = OrderStatus.CANCELLED.value
        order.cancelled_at = now
    if expired:
        await db.commit()
    return len(expired)
