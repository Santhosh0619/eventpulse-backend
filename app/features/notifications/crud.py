"""Database operations for notifications."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.notifications.models import Notification


async def create(db: AsyncSession, *, commit: bool = True, **fields) -> Notification:
    """Create and persist a notification.

    When ``commit`` is ``False`` the row is only flushed, so the write joins the
    caller's open transaction (e.g. order confirmation) and the caller owns the
    commit. This keeps the triggering action atomic.
    """
    notification = Notification(**fields)
    db.add(notification)
    if commit:
        await db.commit()
    else:
        await db.flush()
    await db.refresh(notification)
    return notification


async def get(db: AsyncSession, notification_id: uuid.UUID) -> Notification | None:
    """Return a notification by id, or ``None``."""
    return await db.get(Notification, notification_id)


async def list_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[Notification]:
    """Return a user's notifications, newest first."""
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
    )
    return list(result.scalars().all())


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Return the number of unread notifications for a user."""
    result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
    )
    return int(result.scalar_one())


async def mark_read(db: AsyncSession, notification: Notification) -> Notification:
    """Mark a single notification as read."""
    notification.is_read = True
    notification.read_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(notification)
    return notification


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Mark all of a user's unread notifications as read. Returns the count."""
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .values(is_read=True, read_at=datetime.now(UTC))
    )
    await db.commit()
    return result.rowcount or 0
