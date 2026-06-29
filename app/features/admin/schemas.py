"""Pydantic schemas for the admin feature."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.shared.base_schemas import ORMSchema


class AdminUserRead(ORMSchema):
    """Administrative view of a user account."""

    id: uuid.UUID
    email: EmailStr
    role: str
    is_active: bool
    is_verified: bool
    created_at: datetime


class AdminUserUpdate(BaseModel):
    """Editable user fields for administrators (all optional)."""

    role: str | None = None
    is_active: bool | None = None


class AdminOrgRead(ORMSchema):
    """Administrative view of an organization."""

    id: uuid.UUID
    name: str
    slug: str
    contact_email: str
    is_verified: bool
    created_at: datetime


class FeatureEventRequest(BaseModel):
    """Payload to toggle an event's featured flag."""

    is_featured: bool


class AuditLogRead(ORMSchema):
    """A single audit log entry."""

    id: uuid.UUID
    user_id: uuid.UUID | None = None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None = None
    old_values: dict | None = None
    new_values: dict | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime


class AdminDashboard(BaseModel):
    """Platform-wide counts for the admin dashboard."""

    total_users: int
    total_organizations: int
    unverified_organizations: int
    total_events: int
    draft_events: int
    total_orders: int
    total_audit_logs: int = Field(..., description="Total recorded audit log entries")
