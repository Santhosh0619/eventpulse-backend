"""SQLAlchemy model for payments (Table 11)."""

import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel


class Payment(BaseModel):
    """A financial ledger entry mapping an order to a Stripe PaymentIntent."""

    __tablename__ = "payments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="INR", server_default=text("'INR'")
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, server_default=text("0")
    )
    refund_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    stripe_receipt_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # DB column is "metadata"; the Python attribute is renamed to avoid clashing
    # with SQLAlchemy's reserved ``MetaData`` attribute.
    payment_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'refunded', "
            "'partially_refunded')",
            name="ck_payments_status",
        ),
        CheckConstraint("amount >= 0", name="ck_payments_amount"),
        CheckConstraint("refund_amount <= amount", name="ck_payments_refund_amount"),
        Index("ix_payments_order_id", "order_id"),
        Index("ix_payments_status", "status"),
    )
