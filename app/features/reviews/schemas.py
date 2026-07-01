"""Pydantic schemas for the reviews feature."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.shared.base_schemas import ORMSchema


class ReviewCreate(BaseModel):
    """Payload for submitting a review."""

    rating: int = Field(..., ge=1, le=5)
    title: str | None = Field(default=None, max_length=200)
    comment: str | None = None


class ReviewUpdate(BaseModel):
    """Payload for editing one's own review."""

    rating: int | None = Field(default=None, ge=1, le=5)
    title: str | None = Field(default=None, max_length=200)
    comment: str | None = None


class ReviewRead(ORMSchema):
    """Review representation."""

    id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID
    rating: int
    title: str | None = None
    comment: str | None = None
    is_visible: bool
    moderation_status: str
    organizer_response: str | None = None
    responded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OrganizerResponseRequest(BaseModel):
    """Payload for an organizer replying to a review."""

    response: str = Field(..., min_length=1)


class VisibilityRequest(BaseModel):
    """Payload for an admin toggling a review's visibility."""

    is_visible: bool


class ReviewSummary(BaseModel):
    """Aggregate rating statistics for an event."""

    event_id: uuid.UUID
    total_reviews: int
    average_rating: float
    distribution: dict[int, int]
