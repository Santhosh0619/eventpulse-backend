"""Pydantic schemas for the orders feature."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.shared.base_schemas import ORMSchema


class OrderCreateItem(BaseModel):
    """A requested ticket tier and quantity within a new order."""

    ticket_type_id: uuid.UUID
    quantity: int = Field(..., gt=0, le=50)


class OrderCreate(BaseModel):
    """Payload for placing an order."""

    event_id: uuid.UUID
    items: list[OrderCreateItem] = Field(..., min_length=1)
    notes: str | None = None


class OrderItemRead(ORMSchema):
    """Order line item representation."""

    id: uuid.UUID
    ticket_type_id: uuid.UUID | None = None
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class OrderRead(ORMSchema):
    """Order representation including its line items."""

    id: uuid.UUID
    order_number: str
    user_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = None
    status: str
    total_amount: Decimal
    currency: str
    notes: str | None = None
    expires_at: datetime | None = None
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    items: list[OrderItemRead] = Field(default_factory=list)
