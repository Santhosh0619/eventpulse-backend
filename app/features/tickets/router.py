"""Ticket type endpoints: CRUD per event plus availability."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies import DBSession, get_current_user
from app.features.tickets import services
from app.features.tickets.models import TicketType
from app.features.tickets.schemas import (
    AvailabilityResponse,
    TicketTypeCreate,
    TicketTypeRead,
    TicketTypeUpdate,
)
from app.features.users.models import User

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "/events/{event_id}/ticket-types",
    response_model=TicketTypeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a ticket type",
)
async def create_ticket_type(
    event_id: uuid.UUID,
    payload: TicketTypeCreate,
    current_user: CurrentUser,
    db: DBSession,
) -> TicketType:
    """Create a ticket tier for an event (org admin or owner)."""
    return await services.create_tier(
        db, event_id, current_user, payload.model_dump(exclude_none=True)
    )


@router.get(
    "/events/{event_id}/ticket-types",
    response_model=list[TicketTypeRead],
    summary="List ticket types",
)
async def list_ticket_types(event_id: uuid.UUID, db: DBSession) -> list[TicketType]:
    """List an event's ticket tiers (public)."""
    return await services.list_tiers(db, event_id)


@router.put(
    "/events/{event_id}/ticket-types/{type_id}",
    response_model=TicketTypeRead,
    summary="Update a ticket type",
)
async def update_ticket_type(
    event_id: uuid.UUID,
    type_id: uuid.UUID,
    payload: TicketTypeUpdate,
    current_user: CurrentUser,
    db: DBSession,
) -> TicketType:
    """Update a ticket tier (org admin or owner)."""
    return await services.update_tier(
        db, event_id, type_id, current_user, payload.model_dump(exclude_unset=True)
    )


@router.delete(
    "/events/{event_id}/ticket-types/{type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a ticket type",
)
async def delete_ticket_type(
    event_id: uuid.UUID,
    type_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> None:
    """Delete a ticket tier (org admin or owner)."""
    await services.delete_tier(db, event_id, type_id, current_user)


@router.get(
    "/events/{event_id}/availability",
    response_model=AvailabilityResponse,
    summary="Get ticket availability",
)
async def get_availability(event_id: uuid.UUID, db: DBSession) -> AvailabilityResponse:
    """Return availability across an event's ticket tiers (public)."""
    return await services.get_availability(db, event_id)
