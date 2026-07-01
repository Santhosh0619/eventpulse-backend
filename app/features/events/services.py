"""Business logic for events: lifecycle, search, and permissions."""

import hashlib
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.core.gemini import GeminiError, get_gemini
from app.features.categories import services as categories_services
from app.features.events import crud
from app.features.events.models import Event
from app.features.events.schemas import EventRead
from app.features.organizations import services as orgs_services
from app.features.users.models import User
from app.shared.base_schemas import PaginatedResponse
from app.shared.enums import AuditAction, EventStatus, OrgMemberRole
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
    event = await crud.create_event(
        db, slug=slug, status=EventStatus.DRAFT.value, commit=False, **payload
    )

    from app.features.admin import services as admin_services

    await admin_services.log_action(
        db,
        action=AuditAction.EVENT_CREATED.value,
        entity_type="event",
        entity_id=event.id,
        user_id=user.id,
        new_values={"title": event.title, "status": event.status},
        commit=False,
    )
    await db.commit()
    await db.refresh(event)
    await _invalidate_event_lists()
    return event


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
        await _invalidate_event_lists()
    return event


async def delete_event(db: AsyncSession, event_id: uuid.UUID, user: User) -> None:
    """Delete an event (requires org admin or owner)."""
    event = await _require_event(db, event_id)
    await _require_org_role(db, event.organization_id, user, ADMIN_ROLES)
    await crud.delete_event(db, event)
    await _invalidate_event_lists()


async def publish_event(db: AsyncSession, event_id: uuid.UUID, user: User) -> Event:
    """Publish an event after validating required fields (org admin or owner).

    Requires complete event details and at least one active ticket type.
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

    # Phase 5 requirement: an event must have at least one active ticket type.
    from app.features.tickets import services as tickets_services

    if not await tickets_services.has_active_ticket_type(db, event.id):
        raise BadRequestError("Cannot publish: the event has no active ticket types")

    # Log first (commit=False) so the audit row and the status change commit
    # together in crud.update_status's single transaction.
    await _log_status_change(
        db, event, user, AuditAction.EVENT_PUBLISHED.value, EventStatus.PUBLISHED.value
    )
    updated = await crud.update_status(db, event, EventStatus.PUBLISHED.value)
    await _invalidate_event_lists()
    return updated


async def cancel_event(db: AsyncSession, event_id: uuid.UUID, user: User) -> Event:
    """Cancel an event (requires org admin or owner)."""
    event = await _require_event(db, event_id)
    await _require_org_role(db, event.organization_id, user, ADMIN_ROLES)
    await _log_status_change(
        db, event, user, AuditAction.EVENT_CANCELLED.value, EventStatus.CANCELLED.value
    )
    updated = await crud.update_status(db, event, EventStatus.CANCELLED.value)
    await _invalidate_event_lists()
    return updated


async def _log_status_change(
    db: AsyncSession, event: Event, user: User, action: str, new_status: str
) -> None:
    """Record an event lifecycle transition (flushed; caller's commit persists it)."""
    from app.features.admin import services as admin_services

    await admin_services.log_action(
        db,
        action=action,
        entity_type="event",
        entity_id=event.id,
        user_id=user.id,
        new_values={"status": new_status},
        commit=False,
    )


def _list_key(*, page: int, limit: int, **filters) -> str:
    """Build a stable cache key for a search-events query from its parameters."""
    blob = json.dumps(
        {"page": page, "limit": limit, **filters}, sort_keys=True, default=str
    )
    digest = hashlib.sha256(blob.encode()).hexdigest()[:16]
    return f"{cache.EVENT_LIST_PREFIX}{digest}"


async def _invalidate_event_lists() -> None:
    """Drop all cached event listings (called after any event mutation)."""
    await cache.invalidate_prefix(cache.EVENT_LIST_PREFIX)


async def search_events(
    db: AsyncSession, *, page: int, limit: int, **filters
) -> PaginatedResponse:
    """Search events with filters; defaults to published events (cached 5m)."""
    key = _list_key(page=page, limit=limit, **filters)
    cached = await cache.get_json(key)
    if cached is not None:
        return PaginatedResponse[EventRead].model_validate(cached)

    result = await crud.search_events(db, page=page, limit=limit, **filters)
    payload = PaginatedResponse[EventRead](
        items=[EventRead.model_validate(e) for e in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
        pages=result.pages,
    )
    await cache.set_json(key, payload.model_dump(mode="json"), cache.TTL_EVENT_LIST)
    return payload


async def get_featured(db: AsyncSession, limit: int = 10) -> list[Event]:
    """Return featured published events."""
    return await crud.get_featured(db, limit=limit)


def _fallback_description(keywords: list[str], tone: str) -> str:
    """Return a simple templated description when AI generation is unavailable."""
    if len(keywords) > 1:
        topics = f"{', '.join(keywords[:-1])} and {keywords[-1]}"
    else:
        topics = keywords[0]
    return (
        f"Join us for an unforgettable event featuring {topics}. "
        "Whether you're a first-timer or a returning guest, there's something "
        "here for everyone. Reserve your spot today and be part of the experience."
    )


async def generate_event_description(
    keywords: list[str], tone: str = "professional"
) -> tuple[str, bool]:
    """Draft an event description from keywords via Gemini, with a fallback.

    Returns ``(description, ai_generated)``. Degrades to a templated description
    when Gemini is unconfigured, errors, or returns unusable output.
    """
    gemini = get_gemini()
    if gemini.is_configured:
        prompt = (
            f"Write a compelling, {tone} event description of 2-3 short "
            "paragraphs for a marketing page, based on these keywords: "
            f"{', '.join(keywords)}. Do not invent a specific date, ticket "
            "price, or venue name. Return only the description text, with no "
            "title, preamble, or markdown."
        )
        try:
            text = await gemini.generate_text(prompt, temperature=0.8)
            cleaned = text.strip()
            if cleaned:
                return cleaned, True
        except GeminiError:
            pass
    return _fallback_description(keywords, tone), False
