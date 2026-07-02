"""Pydantic response schemas for analytics (read-only aggregations)."""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class DailySales(BaseModel):
    """Revenue and order count for a single day."""

    day: date
    revenue: Decimal
    orders: int


class TierSales(BaseModel):
    """Sales aggregated for a single ticket tier."""

    ticket_type_id: uuid.UUID
    name: str
    tickets_sold: int
    revenue: Decimal


class SalesAnalytics(BaseModel):
    """Sales breakdown for one event."""

    event_id: uuid.UUID
    total_revenue: Decimal
    total_orders: int
    total_tickets_sold: int
    currency: str
    daily: list[DailySales]
    tiers: list[TierSales]


class HourlyCheckIns(BaseModel):
    """Check-in count for a single hour of the day (0-23, UTC)."""

    hour: int
    count: int


class AttendanceAnalytics(BaseModel):
    """Attendance and check-in breakdown for one event."""

    event_id: uuid.UUID
    total: int
    checked_in: int
    not_checked_in: int
    check_in_rate: float
    hourly: list[HourlyCheckIns]


class OrgOverview(BaseModel):
    """Aggregate metrics across all of an organization's events."""

    organization_id: uuid.UUID
    total_events: int
    published_events: int
    upcoming_events: int
    total_revenue: Decimal
    total_orders: int
    total_tickets_sold: int
    total_attendees: int


class PlatformDashboard(BaseModel):
    """Platform-wide metrics for administrators."""

    total_users: int
    total_organizations: int
    total_events: int
    total_orders: int
    total_revenue: Decimal
    total_tickets_sold: int


class AiAnalyticsSummary(BaseModel):
    """Natural-language summary of an event's analytics."""

    event_id: uuid.UUID
    summary: str
    generated_by_ai: bool
