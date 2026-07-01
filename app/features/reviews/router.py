"""Review endpoints: submit, list, summary, edit, respond, moderate."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies import DBSession, get_current_user, require_role
from app.features.reviews import services
from app.features.reviews.models import Review
from app.features.reviews.schemas import (
    OrganizerResponseRequest,
    ReviewCreate,
    ReviewRead,
    ReviewSummary,
    ReviewUpdate,
    VisibilityRequest,
)
from app.features.users.models import User
from app.shared.enums import UserRole

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]
AdminRequired = Depends(require_role(UserRole.ADMIN.value))


@router.post(
    "/events/{event_id}/reviews",
    response_model=ReviewRead,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a review",
)
async def submit_review(
    event_id: uuid.UUID,
    payload: ReviewCreate,
    current_user: CurrentUser,
    db: DBSession,
) -> Review:
    """Submit a review for an attended event (one per user per event)."""
    return await services.submit_review(
        db, event_id, current_user, payload.model_dump(exclude_none=True)
    )


@router.get(
    "/events/{event_id}/reviews",
    response_model=list[ReviewRead],
    summary="List reviews",
)
async def list_reviews(event_id: uuid.UUID, db: DBSession) -> list[Review]:
    """List an event's visible reviews (public)."""
    return await services.list_reviews(db, event_id)


@router.get(
    "/events/{event_id}/reviews/summary",
    response_model=ReviewSummary,
    summary="Review summary",
)
async def review_summary(event_id: uuid.UUID, db: DBSession) -> ReviewSummary:
    """Return aggregate rating statistics for an event (public)."""
    return await services.get_summary(db, event_id)


@router.get(
    "/events/{event_id}/reviews/management",
    response_model=list[ReviewRead],
    summary="List all reviews for moderation (org members)",
)
async def list_reviews_for_management(
    event_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> list[Review]:
    """List every review for an event, including hidden/flagged (org members)."""
    return await services.list_reviews_for_management(db, event_id, current_user)


@router.post(
    "/reviews/{review_id}/approve",
    response_model=ReviewRead,
    summary="Approve a flagged review (org members)",
)
async def approve_review(
    review_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> Review:
    """Approve a flagged review: make it visible and mark it approved."""
    return await services.approve_review(db, review_id, current_user)


@router.put("/reviews/{review_id}", response_model=ReviewRead, summary="Edit review")
async def update_review(
    review_id: uuid.UUID,
    payload: ReviewUpdate,
    current_user: CurrentUser,
    db: DBSession,
) -> Review:
    """Edit the caller's own review."""
    return await services.update_review(
        db, review_id, current_user, payload.model_dump(exclude_unset=True)
    )


@router.delete(
    "/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete review",
)
async def delete_review(
    review_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> None:
    """Delete the caller's own review."""
    await services.delete_review(db, review_id, current_user)


@router.post(
    "/reviews/{review_id}/response",
    response_model=ReviewRead,
    summary="Respond to a review",
)
async def respond_to_review(
    review_id: uuid.UUID,
    payload: OrganizerResponseRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> Review:
    """Add an organizer response to a review (org member)."""
    return await services.respond_to_review(
        db, review_id, current_user, payload.response
    )


@router.put(
    "/reviews/{review_id}/visibility",
    response_model=ReviewRead,
    dependencies=[AdminRequired],
    summary="Moderate review visibility",
)
async def set_visibility(
    review_id: uuid.UUID, payload: VisibilityRequest, db: DBSession
) -> Review:
    """Toggle a review's visibility (admin only)."""
    return await services.set_visibility(db, review_id, payload.is_visible)
