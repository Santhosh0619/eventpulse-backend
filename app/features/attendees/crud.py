"""Database operations for attendees."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.attendees.models import Attendee


async def get_attendee(db: AsyncSession, attendee_id: uuid.UUID) -> Attendee | None:
    """Return an attendee by id, or ``None``."""
    return await db.get(Attendee, attendee_id)


async def get_by_ticket_code(db: AsyncSession, code: str) -> Attendee | None:
    """Return an attendee by ticket code, or ``None``."""
    result = await db.execute(select(Attendee).where(Attendee.ticket_code == code))
    return result.scalar_one_or_none()


async def ticket_code_exists(db: AsyncSession, code: str) -> bool:
    """Return ``True`` if a ticket code is already in use."""
    result = await db.execute(select(Attendee.id).where(Attendee.ticket_code == code))
    return result.first() is not None


async def list_for_event(db: AsyncSession, event_id: uuid.UUID) -> list[Attendee]:
    """Return all attendees for an event, ordered by creation time."""
    result = await db.execute(
        select(Attendee)
        .where(Attendee.event_id == event_id)
        .order_by(Attendee.created_at)
    )
    return list(result.scalars().all())


async def count_for_event(db: AsyncSession, event_id: uuid.UUID) -> tuple[int, int]:
    """Return ``(total, checked_in)`` attendee counts for an event."""
    total = (
        await db.execute(
            select(func.count())
            .select_from(Attendee)
            .where(Attendee.event_id == event_id)
        )
    ).scalar_one()
    checked_in = (
        await db.execute(
            select(func.count())
            .select_from(Attendee)
            .where(
                Attendee.event_id == event_id,
                Attendee.check_in_status == "checked_in",
            )
        )
    ).scalar_one()
    return int(total), int(checked_in)
