"""Recommendation endpoints: personalized feed and similar events."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import DBSession, get_current_user
from app.features.recommendations import services
from app.features.recommendations.schemas import RecommendedEvent
from app.features.users.models import User

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get(
    "/events",
    response_model=list[RecommendedEvent],
    summary="Personalized event recommendations",
)
async def personalized_events(
    current_user: CurrentUser,
    db: DBSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[RecommendedEvent]:
    """Return upcoming events recommended for the authenticated user."""
    return await services.get_personalized_recommendations(db, current_user, limit)


@router.get(
    "/events/{event_id}/similar",
    response_model=list[RecommendedEvent],
    summary="Similar events",
)
async def similar_events(
    event_id: uuid.UUID,
    db: DBSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[RecommendedEvent]:
    """Return events similar to the given event (public)."""
    return await services.get_similar_events(db, event_id, limit)
