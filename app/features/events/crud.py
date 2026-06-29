"""Database operations and search for events."""

import uuid
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.features.events.models import Event
from app.shared.enums import EventStatus
from app.shared.pagination import paginate


async def slug_exists(db: AsyncSession, slug: str) -> bool:
    """Return ``True`` if an event already uses the given slug."""
    result = await db.execute(select(Event.id).where(Event.slug == slug))
    return result.first() is not None


async def get_event(db: AsyncSession, event_id: uuid.UUID) -> Event | None:
    """Return an event by id, or ``None``."""
    return await db.get(Event, event_id)


async def get_event_by_slug(db: AsyncSession, slug: str) -> Event | None:
    """Return an event by slug, or ``None``."""
    result = await db.execute(select(Event).where(Event.slug == slug))
    return result.scalar_one_or_none()


async def create_event(db: AsyncSession, *, commit: bool = True, **fields) -> Event:
    """Create and persist an event.

    With ``commit=False`` the row is only flushed so the caller can commit it
    atomically alongside related writes (e.g. an audit log entry).
    """
    event = Event(**fields)
    db.add(event)
    if commit:
        await db.commit()
    else:
        await db.flush()
    await db.refresh(event)
    return event


async def update_event(db: AsyncSession, event: Event, fields: dict) -> Event:
    """Apply fields to an event and persist."""
    for key, value in fields.items():
        setattr(event, key, value)
    await db.commit()
    await db.refresh(event)
    return event


async def update_status(db: AsyncSession, event: Event, status: str) -> Event:
    """Set an event's lifecycle status."""
    event.status = status
    await db.commit()
    await db.refresh(event)
    return event


async def delete_event(db: AsyncSession, event: Event) -> None:
    """Delete an event."""
    await db.delete(event)
    await db.commit()


def _distance_km(lat: float, lng: float) -> ColumnElement[float]:
    """Build a haversine distance (km) SQL expression for the events table."""
    inner = func.cos(func.radians(lat)) * func.cos(
        func.radians(Event.latitude)
    ) * func.cos(func.radians(Event.longitude) - func.radians(lng)) + func.sin(
        func.radians(lat)
    ) * func.sin(func.radians(Event.latitude))
    # Clamp to acos's full valid domain [-1, 1] to avoid float rounding errors.
    return 6371.0 * func.acos(func.greatest(-1.0, func.least(1.0, inner)))


def _build_search_query(
    *,
    status: str | None,
    category_id: uuid.UUID | None,
    city: str | None,
    country: str | None,
    q: str | None,
    tags: list[str] | None,
    start_after: datetime | None,
    start_before: datetime | None,
    is_featured: bool | None,
    organization_id: uuid.UUID | None,
    latitude: float | None,
    longitude: float | None,
    radius_km: float | None,
) -> Select:
    """Compose a filtered, ordered ``Select`` for event search."""
    stmt = select(Event)

    if status is not None:
        stmt = stmt.where(Event.status == status)
    if category_id is not None:
        stmt = stmt.where(Event.category_id == category_id)
    if city is not None:
        stmt = stmt.where(Event.city.ilike(city))
    if country is not None:
        stmt = stmt.where(Event.country.ilike(country))
    if organization_id is not None:
        stmt = stmt.where(Event.organization_id == organization_id)
    if is_featured is not None:
        stmt = stmt.where(Event.is_featured.is_(is_featured))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Event.title.ilike(like)
            | Event.short_description.ilike(like)
            | Event.description.ilike(like)
        )
    if tags:
        stmt = stmt.where(Event.tags.contains(tags))
    if start_after is not None:
        stmt = stmt.where(Event.start_datetime >= start_after)
    if start_before is not None:
        stmt = stmt.where(Event.start_datetime <= start_before)

    if latitude is not None and longitude is not None and radius_km is not None:
        distance = _distance_km(latitude, longitude)
        stmt = stmt.where(
            Event.latitude.isnot(None),
            Event.longitude.isnot(None),
            distance <= radius_km,
        ).order_by(distance)
    else:
        stmt = stmt.order_by(Event.start_datetime)

    return stmt


async def search_events(db: AsyncSession, *, page: int = 1, limit: int = 20, **filters):
    """Return a paginated list of events matching the given filters."""
    stmt = _build_search_query(**filters)
    return await paginate(db, stmt, page=page, limit=limit)


async def get_featured(db: AsyncSession, limit: int = 10) -> list[Event]:
    """Return featured, published, upcoming events."""
    stmt = (
        select(Event)
        .where(
            Event.is_featured.is_(True),
            Event.status == EventStatus.PUBLISHED.value,
            Event.start_datetime >= func.now(),
        )
        .order_by(Event.start_datetime)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
