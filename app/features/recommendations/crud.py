"""Read-only queries for recommendation signals and candidate events.

Like analytics, this module reads directly across other features' models to
gather scoring signals; it performs no writes.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.attendees.models import Attendee
from app.features.events.models import Event
from app.features.orders.models import Order, OrderItem
from app.features.reviews.models import Review
from app.features.tickets.models import TicketType
from app.shared.enums import EventStatus, OrderStatus

_CONFIRMED = OrderStatus.CONFIRMED.value
_PUBLISHED = EventStatus.PUBLISHED.value


async def user_attended_event_ids(
    db: AsyncSession, user_id: uuid.UUID
) -> set[uuid.UUID]:
    """Return the set of event ids the user already has tickets for."""
    rows = (
        (
            await db.execute(
                select(Attendee.event_id).where(Attendee.user_id == user_id).distinct()
            )
        )
        .scalars()
        .all()
    )
    return {r for r in rows if r is not None}


async def user_pref_categories(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Return distinct category ids of events the user has attended."""
    rows = (
        (
            await db.execute(
                select(Event.category_id)
                .join(Attendee, Attendee.event_id == Event.id)
                .where(Attendee.user_id == user_id)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    return {r for r in rows if r is not None}


async def user_pref_cities(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    """Return distinct cities of events the user has attended."""
    rows = (
        (
            await db.execute(
                select(Event.city)
                .join(Attendee, Attendee.event_id == Event.id)
                .where(Attendee.user_id == user_id)
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    return {r for r in rows if r}


async def user_avg_price(db: AsyncSession, user_id: uuid.UUID) -> Decimal | None:
    """Return the user's average paid ticket price across confirmed orders."""
    avg = (
        await db.execute(
            select(func.avg(OrderItem.unit_price))
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(Order.user_id == user_id, Order.status == _CONFIRMED)
        )
    ).scalar_one_or_none()
    return Decimal(avg) if avg is not None else None


def _signal_subqueries():
    """Build the correlated scalar subqueries for per-event scoring signals."""
    min_price = (
        select(func.min(TicketType.price))
        .where(TicketType.event_id == Event.id)
        .correlate(Event)
        .scalar_subquery()
    )
    popularity = (
        select(func.count(Attendee.id))
        .where(Attendee.event_id == Event.id)
        .correlate(Event)
        .scalar_subquery()
    )
    avg_rating = (
        select(func.avg(Review.rating))
        .where(Review.event_id == Event.id, Review.is_visible.is_(True))
        .correlate(Event)
        .scalar_subquery()
    )
    return min_price, popularity, avg_rating


async def candidate_events(
    db: AsyncSession,
    now: datetime,
    exclude_ids: set[uuid.UUID],
    pool_limit: int,
) -> list[Row]:
    """Return up to ``pool_limit`` published, upcoming events with scoring signals.

    Each row is ``(Event, min_price, popularity, avg_rating)``. The pool is
    bounded for performance and ordered by soonest start; scoring/ranking happens
    in the service layer.
    """
    min_price, popularity, avg_rating = _signal_subqueries()
    stmt = (
        select(
            Event,
            min_price.label("min_price"),
            popularity.label("popularity"),
            avg_rating.label("avg_rating"),
        )
        .where(Event.status == _PUBLISHED, Event.start_datetime >= now)
        .order_by(Event.start_datetime.asc())
        .limit(pool_limit)
    )
    if exclude_ids:
        stmt = stmt.where(Event.id.notin_(exclude_ids))
    result = await db.execute(stmt)
    return list(result.all())


async def event_min_price(db: AsyncSession, event_id: uuid.UUID) -> Decimal | None:
    """Return the minimum ticket price for an event, or ``None``."""
    price = (
        await db.execute(
            select(func.min(TicketType.price)).where(TicketType.event_id == event_id)
        )
    ).scalar_one_or_none()
    return Decimal(price) if price is not None else None
