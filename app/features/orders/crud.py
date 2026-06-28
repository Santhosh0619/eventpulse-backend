"""Database operations for orders."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.orders.models import Order
from app.shared.enums import OrderStatus


async def order_number_exists(db: AsyncSession, order_number: str) -> bool:
    """Return ``True`` if an order already uses the given order number."""
    result = await db.execute(
        select(Order.id).where(Order.order_number == order_number)
    )
    return result.first() is not None


async def get_order(db: AsyncSession, order_id: uuid.UUID) -> Order | None:
    """Return an order (with items eagerly loaded) by id, or ``None``."""
    return await db.get(Order, order_id)


async def list_user_orders(db: AsyncSession, user_id: uuid.UUID) -> list[Order]:
    """Return a user's orders, newest first."""
    result = await db.execute(
        select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc())
    )
    return list(result.scalars().all())


async def get_expired_pending(db: AsyncSession, now: datetime) -> list[Order]:
    """Return pending orders whose expiry has passed."""
    result = await db.execute(
        select(Order).where(
            Order.status == OrderStatus.PENDING.value,
            Order.expires_at.isnot(None),
            Order.expires_at < now,
        )
    )
    return list(result.scalars().all())
