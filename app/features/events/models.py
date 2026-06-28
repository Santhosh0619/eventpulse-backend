"""SQLAlchemy model for events (Table 6)."""

from __future__ import annotations

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel
from app.shared.enums import EventStatus


class Event(BaseModel):
    """An event hosted by an organization and classified by a category."""

    __tablename__ = "events"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    venue_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    venue_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    start_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_datetime: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, default="UTC", server_default=text("'UTC'")
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=EventStatus.DRAFT.value,
        server_default=text("'draft'"),
    )
    is_featured: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    max_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tags: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )

    __table_args__ = (
        CheckConstraint(
            "end_datetime > start_datetime", name="ck_events_end_after_start"
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'cancelled', 'completed')",
            name="ck_events_status",
        ),
        Index("ix_events_organization_id", "organization_id"),
        Index("ix_events_category_id", "category_id"),
        Index("ix_events_status", "status"),
        Index("ix_events_city", "city"),
        Index("ix_events_start_datetime", "start_datetime"),
        Index("ix_events_status_start", "status", "start_datetime"),
        Index("ix_events_tags", "tags", postgresql_using="gin"),
        Index("ix_events_lat_lng", "latitude", "longitude"),
    )
