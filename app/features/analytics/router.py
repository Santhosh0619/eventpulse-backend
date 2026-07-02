"""Analytics endpoints: event sales, attendance, org overview, platform dashboard."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import DBSession, get_current_user, require_role
from app.features.analytics import services
from app.features.analytics.schemas import (
    AiAnalyticsSummary,
    AttendanceAnalytics,
    OrgOverview,
    PlatformDashboard,
    SalesAnalytics,
)
from app.features.users.models import User
from app.shared.enums import UserRole

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]
AdminRequired = Depends(require_role(UserRole.ADMIN.value))


@router.get(
    "/events/{event_id}/sales",
    response_model=SalesAnalytics,
    summary="Event sales analytics",
)
async def event_sales(
    event_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> SalesAnalytics:
    """Return revenue, order, and per-tier sales for an event (org member only)."""
    return await services.event_sales(db, event_id, current_user)


@router.get(
    "/events/{event_id}/attendance",
    response_model=AttendanceAnalytics,
    summary="Event attendance analytics",
)
async def event_attendance(
    event_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> AttendanceAnalytics:
    """Return check-in counts, rate, and hourly distribution (org member only)."""
    return await services.event_attendance(db, event_id, current_user)


@router.get(
    "/ai-summary",
    response_model=AiAnalyticsSummary,
    summary="AI analytics summary for an event",
)
async def ai_summary(
    event_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> AiAnalyticsSummary:
    """Return a Gemini natural-language summary of an event's analytics.

    ``event_id`` is a query parameter; the caller must be a member of the event's
    organization. Degrades to a deterministic summary when Gemini is unavailable.
    """
    return await services.event_ai_summary(db, event_id, current_user)


@router.get(
    "/organizations/{org_id}/overview",
    response_model=OrgOverview,
    summary="Organization overview analytics",
)
async def org_overview(
    org_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> OrgOverview:
    """Return aggregate metrics across an organization's events (member only)."""
    return await services.org_overview(db, org_id, current_user)


@router.get(
    "/platform",
    response_model=PlatformDashboard,
    dependencies=[AdminRequired],
    summary="Platform-wide dashboard",
)
async def platform_dashboard(db: DBSession) -> PlatformDashboard:
    """Return platform-wide metrics (admin only)."""
    return await services.platform_dashboard(db)
