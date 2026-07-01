"""Pydantic schemas for the events feature."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.shared.base_schemas import ORMSchema


class GenerateDescriptionRequest(BaseModel):
    """Keywords (and optional tone) used to draft an AI event description."""

    keywords: list[str] = Field(..., min_length=1, max_length=10)
    tone: str = Field(default="professional", max_length=40)

    @model_validator(mode="after")
    def _clean_keywords(self) -> "GenerateDescriptionRequest":
        """Trim keywords and reject an all-empty list."""
        self.keywords = [k.strip() for k in self.keywords if k.strip()]
        if not self.keywords:
            raise ValueError("At least one non-empty keyword is required")
        return self


class GenerateDescriptionResponse(BaseModel):
    """A generated event description and whether AI produced it."""

    description: str
    ai_generated: bool


class EventBase(BaseModel):
    """Fields shared by create/update payloads."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    short_description: str | None = Field(default=None, max_length=500)
    category_id: uuid.UUID | None = None
    venue_name: str | None = Field(default=None, max_length=200)
    venue_address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone: str | None = Field(default=None, max_length=50)
    max_capacity: int | None = Field(default=None, gt=0)
    cover_image_url: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = None


class EventCreate(EventBase):
    """Payload for creating an event."""

    organization_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=300)
    start_datetime: datetime
    end_datetime: datetime

    @model_validator(mode="after")
    def _check_dates(self) -> "EventCreate":
        """Ensure the event ends after it starts."""
        if self.end_datetime <= self.start_datetime:
            raise ValueError("end_datetime must be after start_datetime")
        return self


class EventUpdate(EventBase):
    """Payload for updating an event (all fields optional)."""

    start_datetime: datetime | None = None
    end_datetime: datetime | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> "EventUpdate":
        """Ensure date ordering holds when both are supplied."""
        if (
            self.start_datetime is not None
            and self.end_datetime is not None
            and self.end_datetime <= self.start_datetime
        ):
            raise ValueError("end_datetime must be after start_datetime")
        return self


class EventRead(ORMSchema):
    """Full event representation."""

    id: uuid.UUID
    organization_id: uuid.UUID
    category_id: uuid.UUID | None = None
    title: str
    slug: str
    description: str | None = None
    short_description: str | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    start_datetime: datetime
    end_datetime: datetime
    timezone: str
    status: str
    is_featured: bool
    max_capacity: int | None = None
    cover_image_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
