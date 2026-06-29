"""Admin business logic and the shared ``log_action`` audit utility.

``log_action`` is imported lazily by other features to record significant
mutations. When called from inside an open transaction, pass ``commit=False`` so
the audit row commits atomically with the action it records.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.exceptions import BadRequestError, NotFoundError
from app.features.admin import crud
from app.features.admin.models import AuditLog
from app.features.admin.schemas import AdminDashboard
from app.features.events import services as events_services
from app.features.organizations import services as orgs_services
from app.features.users.models import User
from app.shared.base_schemas import PaginatedResponse
from app.shared.enums import AuditAction, UserRole


async def log_action(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    old_values: dict | None = None,
    new_values: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    commit: bool = True,
) -> AuditLog:
    """Record an action in the audit log. Safe to call from any feature."""
    return await crud.create_audit_log(
        db,
        commit=commit,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        old_values=old_values,
        new_values=new_values,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# --------------------------------------------------------------------------- #
# listings
# --------------------------------------------------------------------------- #


async def list_users(db: AsyncSession, **filters) -> PaginatedResponse:
    """Return a paginated list of users (admin only)."""
    return await crud.list_users(db, **filters)


async def list_organizations(db: AsyncSession, **filters) -> PaginatedResponse:
    """Return a paginated list of organizations (admin only)."""
    return await crud.list_organizations(db, **filters)


async def list_events(db: AsyncSession, **filters) -> PaginatedResponse:
    """Return a paginated list of events across all statuses (admin only)."""
    return await crud.list_events(db, **filters)


async def list_audit_logs(db: AsyncSession, **filters) -> PaginatedResponse:
    """Return a paginated list of audit log entries (admin only)."""
    return await crud.list_audit_logs(db, **filters)


async def dashboard(db: AsyncSession) -> AdminDashboard:
    """Return platform-wide counts for the admin dashboard."""
    return AdminDashboard(**await crud.dashboard_counts(db))


# --------------------------------------------------------------------------- #
# mutations (each writes an atomic audit entry)
# --------------------------------------------------------------------------- #


async def update_user(
    db: AsyncSession,
    *,
    actor: User,
    user_id: uuid.UUID,
    role: str | None,
    is_active: bool | None,
    ip_address: str | None,
    user_agent: str | None,
) -> User:
    """Update a user's role and/or active flag, writing an audit entry."""
    user = await crud.get_user(db, user_id)
    if user is None:
        raise NotFoundError("User not found")
    if role is not None and role not in {r.value for r in UserRole}:
        raise BadRequestError("Invalid role")
    # Prevent an admin from locking themselves out of the admin surface.
    if actor.id == user_id:
        if is_active is False:
            raise BadRequestError("You cannot deactivate your own account")
        if role is not None and role != UserRole.ADMIN.value:
            raise BadRequestError("You cannot remove your own admin role")

    old = {"role": user.role, "is_active": user.is_active}
    role_changed = role is not None and role != user.role
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    new = {"role": user.role, "is_active": user.is_active}

    await log_action(
        db,
        action=(
            AuditAction.USER_ROLE_CHANGED.value
            if role_changed
            else AuditAction.USER_UPDATED.value
        ),
        entity_type="user",
        entity_id=user.id,
        user_id=actor.id,
        old_values=old,
        new_values=new,
        ip_address=ip_address,
        user_agent=user_agent,
        commit=False,
    )
    await db.commit()
    await db.refresh(user)
    return user


async def verify_organization(
    db: AsyncSession,
    *,
    actor: User,
    org_id: uuid.UUID,
    ip_address: str | None,
    user_agent: str | None,
):
    """Mark an organization as verified, writing an audit entry."""
    org = await orgs_services.get_organization(db, org_id)  # 404 if missing
    old = {"is_verified": org.is_verified}
    org.is_verified = True
    await log_action(
        db,
        action=AuditAction.ORG_VERIFIED.value,
        entity_type="organization",
        entity_id=org.id,
        user_id=actor.id,
        old_values=old,
        new_values={"is_verified": True},
        ip_address=ip_address,
        user_agent=user_agent,
        commit=False,
    )
    await db.commit()
    await db.refresh(org)
    return org


async def feature_event(
    db: AsyncSession,
    *,
    actor: User,
    event_id: uuid.UUID,
    is_featured: bool,
    ip_address: str | None,
    user_agent: str | None,
):
    """Set an event's featured flag, writing an audit entry."""
    event = await events_services.get_event(db, event_id)  # 404 if missing
    old = {"is_featured": event.is_featured}
    event.is_featured = is_featured
    await log_action(
        db,
        action=AuditAction.EVENT_FEATURED.value,
        entity_type="event",
        entity_id=event.id,
        user_id=actor.id,
        old_values=old,
        new_values={"is_featured": is_featured},
        ip_address=ip_address,
        user_agent=user_agent,
        commit=False,
    )
    await db.commit()
    await db.refresh(event)
    # Featuring changes discovery listings (is_featured filter / featured feed).
    await cache.invalidate_prefix(cache.EVENT_LIST_PREFIX)
    return event
