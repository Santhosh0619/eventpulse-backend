"""Event endpoints: CRUD, search/discovery, publish/cancel."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import DBSession, get_current_user
from app.features.events import services
from app.features.events.models import Event
from app.features.events.schemas import (
    EventCreate,
    EventRead,
    EventUpdate,
    GenerateDescriptionRequest,
    GenerateDescriptionResponse,
)
from app.features.recommendations import ai as recommendations_ai
from app.features.recommendations.schemas import AiRecommendedEvent
from app.features.users.models import User
from app.shared.base_schemas import PaginatedResponse
from app.shared.enums import EventStatus

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "",
    response_model=EventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an event",
)
async def create_event(
    payload: EventCreate, current_user: CurrentUser, db: DBSession
) -> Event:
    """Create a draft event (requires org membership)."""
    return await services.create_event(
        db, current_user, payload.model_dump(exclude_none=True)
    )


@router.post(
    "/generate-description",
    response_model=GenerateDescriptionResponse,
    summary="AI-generate an event description from keywords",
)
async def generate_description(
    payload: GenerateDescriptionRequest,
    current_user: CurrentUser,
) -> GenerateDescriptionResponse:
    """Draft an event description from keywords (Gemini, with fallback).

    Requires authentication. Falls back to a templated description when the AI
    service is unavailable so the button always returns usable text.
    """
    description, ai_generated = await services.generate_event_description(
        payload.keywords, payload.tone
    )
    return GenerateDescriptionResponse(
        description=description, ai_generated=ai_generated
    )


@router.get("", response_model=PaginatedResponse[EventRead], summary="Search events")
async def search_events(
    db: DBSession,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category_id: uuid.UUID | None = None,
    city: str | None = None,
    country: str | None = None,
    q: str | None = None,
    tags: Annotated[list[str] | None, Query()] = None,
    start_after: datetime | None = None,
    start_before: datetime | None = None,
    is_featured: bool | None = None,
    organization_id: uuid.UUID | None = None,
    latitude: float | None = Query(None, ge=-90, le=90),
    longitude: float | None = Query(None, ge=-180, le=180),
    radius_km: float | None = Query(None, gt=0),
) -> PaginatedResponse:
    """Search published events with filters and optional proximity search.

    This public endpoint only ever returns published events; non-published
    statuses are never exposed here.
    """
    return await services.search_events(
        db,
        page=page,
        limit=limit,
        status=EventStatus.PUBLISHED.value,
        category_id=category_id,
        city=city,
        country=country,
        q=q,
        tags=tags,
        start_after=start_after,
        start_before=start_before,
        is_featured=is_featured,
        organization_id=organization_id,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
    )


@router.get("/featured", response_model=list[EventRead], summary="List featured events")
async def featured_events(
    db: DBSession, limit: int = Query(10, ge=1, le=50)
) -> list[Event]:
    """Return featured, published, upcoming events."""
    return await services.get_featured(db, limit=limit)


@router.get("/slug/{slug}", response_model=EventRead, summary="Get an event by slug")
async def get_event_by_slug(slug: str, db: DBSession) -> Event:
    """Return a single event by its slug (public)."""
    return await services.get_event_by_slug(db, slug)


@router.get("/{event_id}", response_model=EventRead, summary="Get an event")
async def get_event(event_id: uuid.UUID, db: DBSession) -> Event:
    """Return a single event by id (public)."""
    return await services.get_event(db, event_id)


@router.get(
    "/{event_id}/similar",
    response_model=list[AiRecommendedEvent],
    summary="AI-powered similar events",
)
async def similar_events(
    event_id: uuid.UUID,
    db: DBSession,
    limit: Annotated[int, Query(ge=1, le=10)] = 6,
) -> list[AiRecommendedEvent]:
    """Return Gemini-curated events similar to the given event (public).

    Falls back to heuristic similarity ranking when the AI service is unavailable.
    """
    return await recommendations_ai.get_ai_similar(db, event_id, limit)


@router.put("/{event_id}", response_model=EventRead, summary="Update an event")
async def update_event(
    event_id: uuid.UUID,
    payload: EventUpdate,
    current_user: CurrentUser,
    db: DBSession,
) -> Event:
    """Update an event (requires org membership)."""
    return await services.update_event(
        db, event_id, current_user, payload.model_dump(exclude_unset=True)
    )


@router.delete(
    "/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an event",
)
async def delete_event(
    event_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> None:
    """Delete an event (requires org admin or owner)."""
    await services.delete_event(db, event_id, current_user)


@router.post(
    "/{event_id}/publish", response_model=EventRead, summary="Publish an event"
)
async def publish_event(
    event_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> Event:
    """Publish an event (requires org admin or owner)."""
    return await services.publish_event(db, event_id, current_user)


@router.post("/{event_id}/cancel", response_model=EventRead, summary="Cancel an event")
async def cancel_event(
    event_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> Event:
    """Cancel an event (requires org admin or owner)."""
    return await services.cancel_event(db, event_id, current_user)
