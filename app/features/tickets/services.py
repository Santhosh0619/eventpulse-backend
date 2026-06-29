"""Business logic for ticket types and inventory reservations."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.features.events import services as events_services
from app.features.organizations import services as orgs_services
from app.features.tickets import crud
from app.features.tickets.models import TicketType
from app.features.tickets.schemas import AvailabilityResponse, TierAvailability
from app.features.users.models import User
from app.shared.enums import OrgMemberRole

ADMIN_ROLES = (OrgMemberRole.OWNER.value, OrgMemberRole.ADMIN.value)


async def _require_event_admin(db: AsyncSession, event_id: uuid.UUID, user: User):
    """Return the event after verifying the user is an org admin or owner."""
    event = await events_services.get_event(db, event_id)  # raises 404
    role = await orgs_services.get_user_org_role(db, event.organization_id, user.id)
    if role is None or role not in ADMIN_ROLES:
        raise ForbiddenError("Requires organization admin or owner role")
    return event


async def _require_tier_for_event(
    db: AsyncSession, event_id: uuid.UUID, type_id: uuid.UUID
) -> TicketType:
    """Fetch a ticket type and ensure it belongs to the given event."""
    tier = await crud.get_ticket_type(db, type_id)
    if tier is None or tier.event_id != event_id:
        raise NotFoundError("Ticket type not found")
    return tier


def _is_on_sale(tier: TicketType, now: datetime) -> bool:
    """Return whether a tier is currently purchasable."""
    if not tier.is_active:
        return False
    if tier.sale_start is not None and now < tier.sale_start:
        return False
    if tier.sale_end is not None and now > tier.sale_end:
        return False
    return tier.quantity_sold < tier.quantity_total


async def list_tiers(db: AsyncSession, event_id: uuid.UUID) -> list[TicketType]:
    """List an event's ticket types (public)."""
    await events_services.get_event(db, event_id)
    return await crud.list_for_event(db, event_id)


def _availability_key(event_id: uuid.UUID) -> str:
    """Cache key for an event's ticket availability."""
    return f"{cache.AVAILABILITY_PREFIX}{event_id}"


async def create_tier(
    db: AsyncSession, event_id: uuid.UUID, user: User, payload: dict
) -> TicketType:
    """Create a ticket tier for an event (org admin or owner)."""
    await _require_event_admin(db, event_id, user)
    tier = await crud.create_ticket_type(db, event_id=event_id, **payload)
    await cache.delete(_availability_key(event_id))
    return tier


async def update_tier(
    db: AsyncSession,
    event_id: uuid.UUID,
    type_id: uuid.UUID,
    user: User,
    fields: dict,
) -> TicketType:
    """Update a ticket tier (org admin or owner)."""
    await _require_event_admin(db, event_id, user)
    tier = await _require_tier_for_event(db, event_id, type_id)
    if "quantity_total" in fields and fields["quantity_total"] < tier.quantity_sold:
        raise BadRequestError(
            "quantity_total cannot be less than the number already sold"
        )
    if fields:
        await crud.update_ticket_type(db, tier, fields)
        await cache.delete(_availability_key(event_id))
    return tier


async def delete_tier(
    db: AsyncSession, event_id: uuid.UUID, type_id: uuid.UUID, user: User
) -> None:
    """Delete a ticket tier (org admin or owner); blocked once sales exist."""
    await _require_event_admin(db, event_id, user)
    tier = await _require_tier_for_event(db, event_id, type_id)
    if tier.quantity_sold > 0:
        raise ConflictError("Cannot delete a ticket type that has sales")
    await crud.delete_ticket_type(db, tier)
    await cache.delete(_availability_key(event_id))


async def get_availability(
    db: AsyncSession, event_id: uuid.UUID
) -> AvailabilityResponse:
    """Return availability across an event's ticket tiers (public, cached 30s)."""
    await events_services.get_event(db, event_id)  # preserve 404

    key = _availability_key(event_id)
    cached = await cache.get_json(key)
    if cached is not None:
        return AvailabilityResponse(**cached)

    tiers = await crud.list_for_event(db, event_id)
    now = datetime.now(UTC)
    tier_rows = [
        TierAvailability(
            ticket_type_id=t.id,
            name=t.name,
            price=t.price,
            currency=t.currency,
            quantity_total=t.quantity_total,
            quantity_sold=t.quantity_sold,
            quantity_available=t.quantity_total - t.quantity_sold,
            is_on_sale=_is_on_sale(t, now),
        )
        for t in tiers
    ]
    total_available = sum(r.quantity_available for r in tier_rows if r.is_on_sale)
    response = AvailabilityResponse(
        event_id=event_id, total_available=total_available, tiers=tier_rows
    )
    await cache.set_json(key, response.model_dump(mode="json"), cache.TTL_AVAILABILITY)
    return response


async def has_active_ticket_type(db: AsyncSession, event_id: uuid.UUID) -> bool:
    """Return whether an event has at least one active ticket type."""
    return await crud.has_active(db, event_id)


async def atomic_reserve(
    db: AsyncSession, type_id: uuid.UUID, quantity: int
) -> TicketType:
    """Reserve ``quantity`` tickets atomically (SELECT ... FOR UPDATE).

    Increments ``quantity_sold`` after locking the row. Does NOT commit — the
    caller (order placement) owns the surrounding transaction.

    Raises:
        NotFoundError: If the tier does not exist.
        BadRequestError: If the tier is inactive or lacks enough inventory.
    """
    tier = await crud.lock_ticket_type(db, type_id)
    if tier is None:
        raise NotFoundError("Ticket type not found")
    if not tier.is_active:
        raise BadRequestError("This ticket type is not on sale")
    if tier.quantity_sold + quantity > tier.quantity_total:
        raise BadRequestError("Not enough tickets available")
    tier.quantity_sold += quantity
    await db.flush()
    return tier


async def release(
    db: AsyncSession, type_id: uuid.UUID, quantity: int
) -> TicketType | None:
    """Release ``quantity`` previously reserved tickets (on cancel/expiry).

    Does NOT commit — the caller owns the transaction.
    """
    tier = await crud.lock_ticket_type(db, type_id)
    if tier is None:
        return None
    tier.quantity_sold = max(0, tier.quantity_sold - quantity)
    await db.flush()
    return tier
