"""SQLAlchemy model for ticket types / tiers (Table 7)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class TicketType(BaseModel):
    """A purchasable ticket tier for an event, with pricing and inventory."""

    __tablename__ = "ticket_types"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="INR", server_default=text("'INR'")
    )
    quantity_total: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_sold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    sale_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sale_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    max_per_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=text("10")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_ticket_types_price"),
        CheckConstraint("quantity_total > 0", name="ck_ticket_types_qty_total"),
        CheckConstraint("quantity_sold >= 0", name="ck_ticket_types_qty_sold"),
        CheckConstraint("max_per_order > 0", name="ck_ticket_types_max_per_order"),
        CheckConstraint(
            "quantity_sold <= quantity_total", name="ck_ticket_types_not_oversold"
        ),
        Index("ix_ticket_types_event_id", "event_id"),
        Index("ix_ticket_types_event_active", "event_id", "is_active"),
    )
