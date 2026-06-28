"""Pydantic schemas for the tickets feature."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.shared.base_schemas import ORMSchema


class TicketTypeCreate(BaseModel):
    """Payload for creating a ticket tier."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    price: Decimal = Field(..., ge=0, max_digits=10, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    quantity_total: int = Field(..., gt=0)
    sale_start: datetime | None = None
    sale_end: datetime | None = None
    max_per_order: int = Field(default=10, gt=0)
    is_active: bool = True
    sort_order: int = 0


class TicketTypeUpdate(BaseModel):
    """Editable ticket tier fields (all optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    quantity_total: int | None = Field(default=None, gt=0)
    sale_start: datetime | None = None
    sale_end: datetime | None = None
    max_per_order: int | None = Field(default=None, gt=0)
    is_active: bool | None = None
    sort_order: int | None = None


class TicketTypeRead(ORMSchema):
    """Ticket tier representation."""

    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    description: str | None = None
    price: Decimal
    currency: str
    quantity_total: int
    quantity_sold: int
    sale_start: datetime | None = None
    sale_end: datetime | None = None
    max_per_order: int
    is_active: bool
    sort_order: int


class TierAvailability(BaseModel):
    """Availability for a single ticket tier."""

    ticket_type_id: uuid.UUID
    name: str
    price: Decimal
    currency: str
    quantity_total: int
    quantity_sold: int
    quantity_available: int
    is_on_sale: bool


class AvailabilityResponse(BaseModel):
    """Availability across all of an event's ticket tiers."""

    event_id: uuid.UUID
    total_available: int
    tiers: list[TierAvailability]
