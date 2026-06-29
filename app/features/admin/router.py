"""Admin endpoints: dashboard, user/org/event management, audit log viewer.

Every endpoint requires the platform ``admin`` role.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.dependencies import DBSession, require_role
from app.features.admin import services
from app.features.admin.schemas import (
    AdminDashboard,
    AdminOrgRead,
    AdminUserRead,
    AdminUserUpdate,
    AuditLogRead,
    FeatureEventRequest,
)
from app.features.events.schemas import EventRead
from app.features.users.models import User
from app.shared.base_schemas import PaginatedResponse
from app.shared.enums import UserRole

router = APIRouter()

# Enforces the admin role and yields the acting admin user.
AdminUser = Annotated[User, Depends(require_role(UserRole.ADMIN.value))]


def _client_info(request: Request) -> tuple[str | None, str | None]:
    """Extract ``(ip_address, user_agent)`` from the request for the audit trail."""
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


@router.get("/dashboard", response_model=AdminDashboard, summary="Admin dashboard")
async def dashboard(admin: AdminUser, db: DBSession) -> AdminDashboard:
    """Return platform-wide counts for administrators."""
    return await services.dashboard(db)


@router.get(
    "/users", response_model=PaginatedResponse[AdminUserRead], summary="List users"
)
async def list_users(
    admin: AdminUser,
    db: DBSession,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    role: str | None = None,
    is_active: bool | None = None,
    q: str | None = None,
) -> PaginatedResponse:
    """List user accounts with optional role/active/email filters."""
    return await services.list_users(
        db, page=page, limit=limit, role=role, is_active=is_active, q=q
    )


@router.put("/users/{user_id}", response_model=AdminUserRead, summary="Update a user")
async def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    admin: AdminUser,
    db: DBSession,
    request: Request,
) -> User:
    """Update a user's role and/or active status (audited)."""
    ip, ua = _client_info(request)
    return await services.update_user(
        db,
        actor=admin,
        user_id=user_id,
        role=payload.role,
        is_active=payload.is_active,
        ip_address=ip,
        user_agent=ua,
    )


@router.get(
    "/organizations",
    response_model=PaginatedResponse[AdminOrgRead],
    summary="List organizations",
)
async def list_organizations(
    admin: AdminUser,
    db: DBSession,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    is_verified: bool | None = None,
    q: str | None = None,
) -> PaginatedResponse:
    """List organizations with optional verification/name filters."""
    return await services.list_organizations(
        db, page=page, limit=limit, is_verified=is_verified, q=q
    )


@router.put(
    "/organizations/{org_id}/verify",
    response_model=AdminOrgRead,
    summary="Verify an organization",
)
async def verify_organization(
    org_id: uuid.UUID, admin: AdminUser, db: DBSession, request: Request
):
    """Mark an organization as verified (audited)."""
    ip, ua = _client_info(request)
    return await services.verify_organization(
        db, actor=admin, org_id=org_id, ip_address=ip, user_agent=ua
    )


@router.get(
    "/events", response_model=PaginatedResponse[EventRead], summary="List events"
)
async def list_events(
    admin: AdminUser,
    db: DBSession,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> PaginatedResponse:
    """List events across all statuses with optional filters."""
    return await services.list_events(
        db, page=page, limit=limit, status=status, organization_id=organization_id
    )


@router.put(
    "/events/{event_id}/feature",
    response_model=EventRead,
    summary="Set an event's featured flag",
)
async def feature_event(
    event_id: uuid.UUID,
    payload: FeatureEventRequest,
    admin: AdminUser,
    db: DBSession,
    request: Request,
):
    """Set or clear an event's featured flag (audited)."""
    ip, ua = _client_info(request)
    return await services.feature_event(
        db,
        actor=admin,
        event_id=event_id,
        is_featured=payload.is_featured,
        ip_address=ip,
        user_agent=ua,
    )


@router.get(
    "/audit-logs",
    response_model=PaginatedResponse[AuditLogRead],
    summary="View audit logs",
)
async def list_audit_logs(
    admin: AdminUser,
    db: DBSession,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    action: str | None = None,
    entity_type: str | None = None,
    user_id: uuid.UUID | None = None,
) -> PaginatedResponse:
    """View audit log entries with optional action/entity/user filters."""
    return await services.list_audit_logs(
        db,
        page=page,
        limit=limit,
        action=action,
        entity_type=entity_type,
        user_id=user_id,
    )
