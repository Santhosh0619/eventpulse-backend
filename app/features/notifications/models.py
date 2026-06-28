"""SQLAlchemy model for notifications (Table 13).

``notifications`` has only ``created_at`` (no ``updated_at``), so it derives
directly from ``Base`` rather than ``BaseModel``.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Notification(Base):
    """An in-app/push/email notification delivered to a user."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )
    channel: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="in_app",
        server_default=text("'in_app'"),
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "channel IN ('in_app', 'push', 'email')",
            name="ck_notifications_channel",
        ),
        Index("ix_notifications_user_id", "user_id"),
        Index("ix_notifications_user_read", "user_id", "is_read"),
        Index("ix_notifications_type", "type"),
        Index("ix_notifications_created_at", "created_at"),
    )
