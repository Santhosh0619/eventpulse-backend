"""Pydantic schemas for the notifications feature."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.shared.base_schemas import ORMSchema


class NotificationRead(ORMSchema):
    """Notification representation."""

    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    message: str
    data: dict = Field(default_factory=dict)
    channel: str
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime


class UnreadCountResponse(BaseModel):
    """Count of unread notifications for the current user."""

    unread: int


class MessageResponse(BaseModel):
    """Generic success message."""

    message: str
