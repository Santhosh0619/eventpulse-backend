"""Aggregate SQL queries for analytics.

This module is read-only and reporting-oriented: it reads directly across other
features' models (Order, Attendee, Event, ...) to compute aggregates. Behavioural
cross-feature access still goes through services; only authorization in the
analytics services layer guards these queries.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.attendees.models import Attendee
from app.features.events.models import Event
from app.features.orders.models import Order, OrderItem
from app.features.organizations.models import Organization
from app.features.tickets.models import TicketType
from app.features.users.models import User
from app.shared.enums import CheckInStatus, EventStatus, OrderStatus

_CONFIRMED = OrderStatus.CONFIRMED.value
_ZERO = Decimal("0.00")


# --------------------------------------------------------------------------- #
# event sales
# --------------------------------------------------------------------------- #


async def event_sales_totals(
    db: AsyncSession, event_id: uuid.UUID
) -> tuple[Decimal, int]:
    """Return ``(total_revenue, total_orders)`` from confirmed orders."""
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Order.total_amount), _ZERO),
                func.count(Order.id),
            ).where(Order.event_id == event_id, Order.status == _CONFIRMED)
        )
    ).one()
    return Decimal(row[0]), int(row[1])


async def event_tickets_sold(db: AsyncSession, event_id: uuid.UUID) -> int:
    """Return the total tickets sold across an event's confirmed orders."""
    total = (
        await db.execute(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(Order.event_id == event_id, Order.status == _CONFIRMED)
        )
    ).scalar_one()
    return int(total)


async def event_currency(db: AsyncSession, event_id: uuid.UUID) -> str:
    """Return the currency of the event's confirmed orders (default ``INR``).

    Scoped to confirmed orders so the reported currency always matches the
    summed revenue (which only counts confirmed orders).
    """
    currency = (
        await db.execute(
            select(Order.currency)
            .where(Order.event_id == event_id, Order.status == _CONFIRMED)
            .order_by(Order.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return currency or "INR"


async def event_daily_sales(db: AsyncSession, event_id: uuid.UUID) -> list[Row]:
    """Return per-day ``(day, revenue, orders)`` rows for confirmed orders."""
    day = func.date(Order.confirmed_at).label("day")
    result = await db.execute(
        select(
            day,
            func.coalesce(func.sum(Order.total_amount), _ZERO).label("revenue"),
            func.count(Order.id).label("orders"),
        )
        .where(
            Order.event_id == event_id,
            Order.status == _CONFIRMED,
            Order.confirmed_at.is_not(None),
        )
        .group_by(day)
        .order_by(day)
    )
    return list(result.all())


async def event_tier_sales(db: AsyncSession, event_id: uuid.UUID) -> list[Row]:
    """Return per-tier ``(ticket_type_id, name, tickets_sold, revenue)`` rows."""
    result = await db.execute(
        select(
            TicketType.id.label("ticket_type_id"),
            TicketType.name.label("name"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("tickets_sold"),
            func.coalesce(func.sum(OrderItem.subtotal), _ZERO).label("revenue"),
        )
        .select_from(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .join(TicketType, OrderItem.ticket_type_id == TicketType.id)
        .where(Order.event_id == event_id, Order.status == _CONFIRMED)
        .group_by(TicketType.id, TicketType.name)
        .order_by(TicketType.name)
    )
    return list(result.all())


# --------------------------------------------------------------------------- #
# event attendance
# --------------------------------------------------------------------------- #


async def event_attendance_counts(
    db: AsyncSession, event_id: uuid.UUID
) -> tuple[int, int]:
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
                Attendee.check_in_status == CheckInStatus.CHECKED_IN.value,
            )
        )
    ).scalar_one()
    return int(total), int(checked_in)


async def event_hourly_checkins(db: AsyncSession, event_id: uuid.UUID) -> list[Row]:
    """Return ``(hour, count)`` rows for checked-in attendees, by UTC hour."""
    hour = cast(func.extract("hour", Attendee.checked_in_at), Numeric).label("hour")
    result = await db.execute(
        select(hour, func.count().label("count"))
        .where(
            Attendee.event_id == event_id,
            Attendee.check_in_status == CheckInStatus.CHECKED_IN.value,
            Attendee.checked_in_at.is_not(None),
        )
        .group_by(hour)
        .order_by(hour)
    )
    return list(result.all())


# --------------------------------------------------------------------------- #
# organization overview
# --------------------------------------------------------------------------- #


async def org_event_counts(
    db: AsyncSession, org_id: uuid.UUID, now: datetime
) -> tuple[int, int, int]:
    """Return ``(total_events, published_events, upcoming_events)`` for an org."""
    total = (
        await db.execute(
            select(func.count())
            .select_from(Event)
            .where(Event.organization_id == org_id)
        )
    ).scalar_one()
    published = (
        await db.execute(
            select(func.count())
            .select_from(Event)
            .where(
                Event.organization_id == org_id,
                Event.status == EventStatus.PUBLISHED.value,
            )
        )
    ).scalar_one()
    upcoming = (
        await db.execute(
            select(func.count())
            .select_from(Event)
            .where(
                Event.organization_id == org_id,
                Event.status == EventStatus.PUBLISHED.value,
                Event.start_datetime >= now,
            )
        )
    ).scalar_one()
    return int(total), int(published), int(upcoming)


async def org_sales_totals(db: AsyncSession, org_id: uuid.UUID) -> tuple[Decimal, int]:
    """Return ``(total_revenue, total_orders)`` across all of an org's events."""
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Order.total_amount), _ZERO),
                func.count(Order.id),
            )
            .select_from(Order)
            .join(Event, Order.event_id == Event.id)
            .where(Event.organization_id == org_id, Order.status == _CONFIRMED)
        )
    ).one()
    return Decimal(row[0]), int(row[1])


async def org_tickets_sold(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Return total tickets sold across an org's confirmed orders."""
    total = (
        await db.execute(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .join(Event, Order.event_id == Event.id)
            .where(Event.organization_id == org_id, Order.status == _CONFIRMED)
        )
    ).scalar_one()
    return int(total)


async def org_attendee_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Return the total attendees across all of an org's events."""
    total = (
        await db.execute(
            select(func.count())
            .select_from(Attendee)
            .join(Event, Attendee.event_id == Event.id)
            .where(Event.organization_id == org_id)
        )
    ).scalar_one()
    return int(total)


# --------------------------------------------------------------------------- #
# platform dashboard
# --------------------------------------------------------------------------- #


async def platform_totals(db: AsyncSession) -> dict[str, object]:
    """Return platform-wide counts and revenue for the admin dashboard."""
    users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    orgs = (
        await db.execute(select(func.count()).select_from(Organization))
    ).scalar_one()
    events = (await db.execute(select(func.count()).select_from(Event))).scalar_one()
    order_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Order.total_amount), _ZERO),
                func.count(Order.id),
            ).where(Order.status == _CONFIRMED)
        )
    ).one()
    tickets = (
        await db.execute(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(Order.status == _CONFIRMED)
        )
    ).scalar_one()
    return {
        "total_users": int(users),
        "total_organizations": int(orgs),
        "total_events": int(events),
        "total_revenue": Decimal(order_row[0]),
        "total_orders": int(order_row[1]),
        "total_tickets_sold": int(tickets),
    }
