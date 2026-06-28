"""Business logic for events: lifecycle, search, and permissions."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.features.categories import services as categories_services
from app.features.events import crud
from app.features.events.models import Event
from app.features.organizations import services as orgs_services
from app.features.users.models import User
from app.shared.enums import EventStatus, OrgMemberRole
from app.shared.slug import generate_unique_slug

MEMBER_ROLES = (
    OrgMemberRole.OWNER.value,
    OrgMemberRole.ADMIN.value,
    OrgMemberRole.MEMBER.value,
)
ADMIN_ROLES = (OrgMemberRole.OWNER.value, OrgMemberRole.ADMIN.value)


async def _require_org_role(
    db: AsyncSession, org_id: uuid.UUID, user: User, allowed: tuple[str, ...]
) -> None:
    """Ensure the user has one of ``allowed`` roles in the organization."""
    role = await orgs_services.get_user_org_role(db, org_id, user.id)
    if role is None:
        raise ForbiddenError("You are not a member of this organization")
    if role not in allowed:
        raise ForbiddenError("Insufficient organization role for this action")


async def _require_event(db: AsyncSession, event_id: uuid.UUID) -> Event:
    """Fetch an event or raise 404."""
    event = await crud.get_event(db, event_id)
    if event is None:
        raise NotFoundError("Event not found")
    return event


async def _validate_category(db: AsyncSession, category_id: uuid.UUID | None) -> None:
    """Raise 400 if a category id is provided but does not exist."""
    if category_id is not None:
        category = await categories_services.get_category(db, category_id)
        if category is None:
            raise BadRequestError("Category does not exist")


async def create_event(db: AsyncSession, user: User, payload: dict) -> Event:
    """Create a draft event (requires org membership)."""
    org_id = payload["organization_id"]
    await _require_org_role(db, org_id, user, MEMBER_ROLES)
    await _validate_category(db, payload.get("category_id"))

    slug = await generate_unique_slug(
        payload["title"], lambda candidate: crud.slug_exists(db, candidate)
    )
    return await crud.create_event(
        db, slug=slug, status=EventStatus.DRAFT.value, **payload
    )


async def get_event(db: AsyncSession, event_id: uuid.UUID) -> Event:
    """Return an event by id, or raise 404."""
    return await _require_event(db, event_id)


async def get_event_by_slug(db: AsyncSession, slug: str) -> Event:
    """Return an event by slug, or raise 404."""
    event = await crud.get_event_by_slug(db, slug)
    if event is None:
        raise NotFoundError("Event not found")
    return event


async def update_event(
    db: AsyncSession, event_id: uuid.UUID, user: User, fields: dict
) -> Event:
    """Update an event (requires org membership)."""
    event = await _require_event(db, event_id)
    await _require_org_role(db, event.organization_id, user, MEMBER_ROLES)
    if "category_id" in fields:
        await _validate_category(db, fields["category_id"])
    if fields:
        await crud.update_event(db, event, fields)
    return event


async def delete_event(db: AsyncSession, event_id: uuid.UUID, user: User) -> None:
    """Delete an event (requires org admin or owner)."""
    event = await _require_event(db, event_id)
    await _require_org_role(db, event.organization_id, user, ADMIN_ROLES)
    await crud.delete_event(db, event)


async def publish_event(db: AsyncSession, event_id: uuid.UUID, user: User) -> Event:
    """Publish an event after validating required fields (org admin or owner).

    Per Phase 4, ticket types are NOT required to publish (that check is added in
    Phase 5).
    """
    event = await _require_event(db, event_id)
    await _require_org_role(db, event.organization_id, user, ADMIN_ROLES)

    missing = []
    if not event.title:
        missing.append("title")
    if not event.description:
        missing.append("description")
    if not (event.venue_name or event.venue_address):
        missing.append("venue")
    if not event.start_datetime or not event.end_datetime:
        missing.append("start/end datetime")
    if missing:
        raise BadRequestError(
            f"Cannot publish: missing required fields: {', '.join(missing)}"
        )

    return await crud.update_status(db, event, EventStatus.PUBLISHED.value)


async def cancel_event(db: AsyncSession, event_id: uuid.UUID, user: User) -> Event:
    """Cancel an event (requires org admin or owner)."""
    event = await _require_event(db, event_id)
    await _require_org_role(db, event.organization_id, user, ADMIN_ROLES)
    return await crud.update_status(db, event, EventStatus.CANCELLED.value)


async def search_events(db: AsyncSession, *, page: int, limit: int, **filters):
    """Search events with filters; defaults to published events for discovery."""
    return await crud.search_events(db, page=page, limit=limit, **filters)


async def get_featured(db: AsyncSession, limit: int = 10) -> list[Event]:
    """Return featured published events."""
    return await crud.get_featured(db, limit=limit)
