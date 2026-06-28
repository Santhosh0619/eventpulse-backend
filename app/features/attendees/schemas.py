"""Pydantic schemas for the attendees feature."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.shared.base_schemas import ORMSchema


class AttendeeRead(ORMSchema):
    """Attendee record representation."""

    id: uuid.UUID
    event_id: uuid.UUID
    order_item_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    ticket_code: str
    first_name: str
    last_name: str
    email: str
    check_in_status: str
    checked_in_at: datetime | None = None
    created_at: datetime


class CheckInRequest(BaseModel):
    """Payload for checking in an attendee by ticket code."""

    ticket_code: str = Field(..., min_length=1, max_length=50)


class CheckInResponse(BaseModel):
    """Result of a check-in attempt."""

    success: bool
    already_checked_in: bool
    message: str
    attendee: AttendeeRead | None = None


class AttendeeStats(BaseModel):
    """Aggregate check-in stats for an event."""

    event_id: uuid.UUID
    total: int
    checked_in: int
    not_checked_in: int
    check_in_rate: float
