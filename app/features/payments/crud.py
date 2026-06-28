"""Database operations for payments."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.payments.models import Payment


async def create_payment(db: AsyncSession, **fields) -> Payment:
    """Create and persist a payment record."""
    payment = Payment(**fields)
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    return payment


async def get_by_intent_id(db: AsyncSession, intent_id: str) -> Payment | None:
    """Return the payment for a Stripe PaymentIntent id, or ``None``."""
    result = await db.execute(
        select(Payment).where(Payment.stripe_payment_intent_id == intent_id)
    )
    return result.scalar_one_or_none()


async def lock_by_intent_id(db: AsyncSession, intent_id: str) -> Payment | None:
    """Return the payment for an intent id, locked FOR UPDATE.

    Serializes concurrent webhook deliveries so a payment is fulfilled once.
    """
    result = await db.execute(
        select(Payment)
        .where(Payment.stripe_payment_intent_id == intent_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def get_latest_for_order(db: AsyncSession, order_id: uuid.UUID) -> Payment | None:
    """Return the most recent payment for an order, or ``None``."""
    result = await db.execute(
        select(Payment)
        .where(Payment.order_id == order_id)
        .order_by(Payment.created_at.desc())
    )
    return result.scalars().first()
