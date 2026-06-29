"""Database operations for the admin feature: audit log + admin listings."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.admin.models import AuditLog
from app.features.events.models import Event
from app.features.orders.models import Order
from app.features.organizations.models import Organization
from app.features.users.models import User
from app.shared.base_schemas import PaginatedResponse
from app.shared.pagination import paginate


async def create_audit_log(
    db: AsyncSession, *, commit: bool = True, **fields
) -> AuditLog:
    """Append an audit log entry.

    With ``commit=False`` the row is only flushed, joining the caller's open
    transaction so the audit record stays atomic with the action it records.
    """
    entry = AuditLog(**fields)
    db.add(entry)
    if commit:
        await db.commit()
    else:
        await db.flush()
    return entry


async def list_audit_logs(
    db: AsyncSession,
    *,
    page: int,
    limit: int,
    action: str | None = None,
    entity_type: str | None = None,
    user_id: uuid.UUID | None = None,
) -> PaginatedResponse:
    """Return a paginated, newest-first list of audit log entries."""
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type is not None:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    return await paginate(db, stmt, page=page, limit=limit)


async def list_users(
    db: AsyncSession,
    *,
    page: int,
    limit: int,
    role: str | None = None,
    is_active: bool | None = None,
    q: str | None = None,
) -> PaginatedResponse:
    """Return a paginated, newest-first list of users with optional filters."""
    stmt = select(User).order_by(User.created_at.desc())
    if role is not None:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%"))
    return await paginate(db, stmt, page=page, limit=limit)


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Return a user by id, or ``None``."""
    return await db.get(User, user_id)


async def list_organizations(
    db: AsyncSession,
    *,
    page: int,
    limit: int,
    is_verified: bool | None = None,
    q: str | None = None,
) -> PaginatedResponse:
    """Return a paginated, newest-first list of organizations."""
    stmt = select(Organization).order_by(Organization.created_at.desc())
    if is_verified is not None:
        stmt = stmt.where(Organization.is_verified.is_(is_verified))
    if q:
        stmt = stmt.where(
            or_(Organization.name.ilike(f"%{q}%"), Organization.slug.ilike(f"%{q}%"))
        )
    return await paginate(db, stmt, page=page, limit=limit)


async def list_events(
    db: AsyncSession,
    *,
    page: int,
    limit: int,
    status: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> PaginatedResponse:
    """Return a paginated, newest-first list of events across all statuses."""
    stmt = select(Event).order_by(Event.created_at.desc())
    if status is not None:
        stmt = stmt.where(Event.status == status)
    if organization_id is not None:
        stmt = stmt.where(Event.organization_id == organization_id)
    return await paginate(db, stmt, page=page, limit=limit)


async def dashboard_counts(db: AsyncSession) -> dict[str, int]:
    """Return the platform-wide counts shown on the admin dashboard."""

    async def _count(stmt) -> int:
        return int((await db.execute(stmt)).scalar_one())

    return {
        "total_users": await _count(select(func.count()).select_from(User)),
        "total_organizations": await _count(
            select(func.count()).select_from(Organization)
        ),
        "unverified_organizations": await _count(
            select(func.count())
            .select_from(Organization)
            .where(Organization.is_verified.is_(False))
        ),
        "total_events": await _count(select(func.count()).select_from(Event)),
        "draft_events": await _count(
            select(func.count()).select_from(Event).where(Event.status == "draft")
        ),
        "total_orders": await _count(select(func.count()).select_from(Order)),
        "total_audit_logs": await _count(select(func.count()).select_from(AuditLog)),
    }
