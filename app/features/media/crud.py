"""Database operations for event media."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.media.models import EventMedia


async def get_media(db: AsyncSession, media_id: uuid.UUID) -> EventMedia | None:
    """Return a media item by id, or ``None``."""
    return await db.get(EventMedia, media_id)


async def list_media(db: AsyncSession, event_id: uuid.UUID) -> list[EventMedia]:
    """Return an event's media ordered by sort_order."""
    result = await db.execute(
        select(EventMedia)
        .where(EventMedia.event_id == event_id)
        .order_by(EventMedia.sort_order, EventMedia.created_at)
    )
    return list(result.scalars().all())


async def next_sort_order(db: AsyncSession, event_id: uuid.UUID) -> int:
    """Return the next sort_order value for an event's media."""
    result = await db.execute(
        select(func.coalesce(func.max(EventMedia.sort_order), -1)).where(
            EventMedia.event_id == event_id
        )
    )
    return int(result.scalar_one()) + 1


async def add_media(db: AsyncSession, **fields) -> EventMedia:
    """Create and persist a media record."""
    media = EventMedia(**fields)
    db.add(media)
    await db.commit()
    await db.refresh(media)
    return media


async def delete_media(db: AsyncSession, media: EventMedia) -> None:
    """Delete a media record."""
    await db.delete(media)
    await db.commit()


async def apply_order(
    db: AsyncSession, event_id: uuid.UUID, ordered_ids: list[uuid.UUID]
) -> list[EventMedia]:
    """Set sort_order for the given media ids in the supplied sequence."""
    items = await list_media(db, event_id)
    by_id = {item.id: item for item in items}
    for position, media_id in enumerate(ordered_ids):
        media = by_id.get(media_id)
        if media is not None:
            media.sort_order = position
    await db.commit()
    return await list_media(db, event_id)
