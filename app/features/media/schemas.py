"""Pydantic schemas for the media feature."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.shared.base_schemas import ORMSchema


class MediaRead(ORMSchema):
    """Event media representation."""

    id: uuid.UUID
    event_id: uuid.UUID
    type: str
    url: str
    thumbnail_url: str | None = None
    caption: str | None = None
    sort_order: int
    file_size_bytes: int | None = None
    created_at: datetime


class MediaUploadResponse(MediaRead):
    """Response returned after uploading a media item."""


class ReorderRequest(BaseModel):
    """Payload specifying the new ordering of media items by id."""

    media_ids: list[uuid.UUID] = Field(..., min_length=1)
