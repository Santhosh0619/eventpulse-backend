"""Business logic and authorization for analytics endpoints."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError
from app.features.analytics import crud
from app.features.analytics.schemas import (
    AttendanceAnalytics,
    DailySales,
    HourlyCheckIns,
    OrgOverview,
    PlatformDashboard,
    SalesAnalytics,
    TierSales,
)
from app.features.events import services as events_services
from app.features.organizations import services as orgs_services
from app.features.users.models import User
from app.shared.enums import OrgMemberRole

MEMBER_ROLES = (
    OrgMemberRole.OWNER.value,
    OrgMemberRole.ADMIN.value,
    OrgMemberRole.MEMBER.value,
)


async def _require_event_member(
    db: AsyncSession, event_id: uuid.UUID, user: User
) -> None:
    """Verify the caller is a member of the event's organization (else 403/404)."""
    event = await events_services.get_event(db, event_id)  # 404 if missing
    role = await orgs_services.get_user_org_role(db, event.organization_id, user.id)
    if role is None or role not in MEMBER_ROLES:
        raise ForbiddenError("You are not authorized for this event")


async def _require_org_member(db: AsyncSession, org_id: uuid.UUID, user: User) -> None:
    """Verify the caller is a member of the organization (else 403/404)."""
    await orgs_services.get_organization(db, org_id)  # 404 if missing
    role = await orgs_services.get_user_org_role(db, org_id, user.id)
    if role is None or role not in MEMBER_ROLES:
        raise ForbiddenError("You are not a member of this organization")


async def event_sales(
    db: AsyncSession, event_id: uuid.UUID, user: User
) -> SalesAnalytics:
    """Return sales analytics for an event (org member only)."""
    await _require_event_member(db, event_id, user)
    revenue, orders = await crud.event_sales_totals(db, event_id)
    return SalesAnalytics(
        event_id=event_id,
        total_revenue=revenue,
        total_orders=orders,
        total_tickets_sold=await crud.event_tickets_sold(db, event_id),
        currency=await crud.event_currency(db, event_id),
        daily=[
            DailySales(day=r.day, revenue=r.revenue, orders=r.orders)
            for r in await crud.event_daily_sales(db, event_id)
        ],
        tiers=[
            TierSales(
                ticket_type_id=r.ticket_type_id,
                name=r.name,
                tickets_sold=r.tickets_sold,
                revenue=r.revenue,
            )
            for r in await crud.event_tier_sales(db, event_id)
        ],
    )


async def event_attendance(
    db: AsyncSession, event_id: uuid.UUID, user: User
) -> AttendanceAnalytics:
    """Return attendance analytics for an event (org member only)."""
    await _require_event_member(db, event_id, user)
    total, checked_in = await crud.event_attendance_counts(db, event_id)
    rate = round(checked_in / total, 4) if total else 0.0
    return AttendanceAnalytics(
        event_id=event_id,
        total=total,
        checked_in=checked_in,
        not_checked_in=total - checked_in,
        check_in_rate=rate,
        hourly=[
            HourlyCheckIns(hour=int(r.hour), count=r.count)
            for r in await crud.event_hourly_checkins(db, event_id)
        ],
    )


async def org_overview(db: AsyncSession, org_id: uuid.UUID, user: User) -> OrgOverview:
    """Return aggregate analytics across an organization's events (member only)."""
    await _require_org_member(db, org_id, user)
    now = datetime.now(UTC)
    total_events, published, upcoming = await crud.org_event_counts(db, org_id, now)
    revenue, orders = await crud.org_sales_totals(db, org_id)
    return OrgOverview(
        organization_id=org_id,
        total_events=total_events,
        published_events=published,
        upcoming_events=upcoming,
        total_revenue=revenue,
        total_orders=orders,
        total_tickets_sold=await crud.org_tickets_sold(db, org_id),
        total_attendees=await crud.org_attendee_count(db, org_id),
    )


async def platform_dashboard(db: AsyncSession) -> PlatformDashboard:
    """Return platform-wide analytics (admin only — enforced at the router)."""
    return PlatformDashboard(**await crud.platform_totals(db))
