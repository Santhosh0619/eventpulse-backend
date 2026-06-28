"""Database operations for ticket types, including atomic inventory updates."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.tickets.models import TicketType


async def get_ticket_type(db: AsyncSession, type_id: uuid.UUID) -> TicketType | None:
    """Return a ticket type by id, or ``None``."""
    return await db.get(TicketType, type_id)


async def list_for_event(
    db: AsyncSession, event_id: uuid.UUID, active_only: bool = False
) -> list[TicketType]:
    """Return an event's ticket types ordered by sort_order."""
    stmt = select(TicketType).where(TicketType.event_id == event_id)
    if active_only:
        stmt = stmt.where(TicketType.is_active.is_(True))
    stmt = stmt.order_by(TicketType.sort_order, TicketType.created_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def has_active(db: AsyncSession, event_id: uuid.UUID) -> bool:
    """Return ``True`` if the event has at least one active ticket type."""
    result = await db.execute(
        select(TicketType.id).where(
            TicketType.event_id == event_id, TicketType.is_active.is_(True)
        )
    )
    return result.first() is not None


async def count_sold(db: AsyncSession, event_id: uuid.UUID) -> int:
    """Return the total tickets sold across an event's tiers."""
    result = await db.execute(
        select(func.coalesce(func.sum(TicketType.quantity_sold), 0)).where(
            TicketType.event_id == event_id
        )
    )
    return int(result.scalar_one())


async def create_ticket_type(db: AsyncSession, **fields) -> TicketType:
    """Create and persist a ticket type."""
    ticket_type = TicketType(**fields)
    db.add(ticket_type)
    await db.commit()
    await db.refresh(ticket_type)
    return ticket_type


async def update_ticket_type(
    db: AsyncSession, ticket_type: TicketType, fields: dict
) -> TicketType:
    """Apply fields to a ticket type and persist."""
    for key, value in fields.items():
        setattr(ticket_type, key, value)
    await db.commit()
    await db.refresh(ticket_type)
    return ticket_type


async def delete_ticket_type(db: AsyncSession, ticket_type: TicketType) -> None:
    """Delete a ticket type."""
    await db.delete(ticket_type)
    await db.commit()


async def lock_ticket_type(db: AsyncSession, type_id: uuid.UUID) -> TicketType | None:
    """Select a ticket type FOR UPDATE to serialize concurrent reservations."""
    result = await db.execute(
        select(TicketType).where(TicketType.id == type_id).with_for_update()
    )
    return result.scalar_one_or_none()
