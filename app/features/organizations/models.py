"""SQLAlchemy models for organizations and their members (Tables 3 and 4)."""

from __future__ import annotations

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
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel
from app.shared.enums import InvitationStatus, OrgMemberRole


class Organization(BaseModel):
    """An entity that hosts events. Created and managed by users."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    stripe_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    members: Mapped[list[OrganizationMember]] = relationship(
        "OrganizationMember",
        back_populates="organization",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_organizations_created_by", "created_by"),
        Index("ix_organizations_is_verified", "is_verified"),
    )


class OrganizationMember(BaseModel):
    """Membership linking a user to an organization with a role."""

    __tablename__ = "organization_members"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=OrgMemberRole.MEMBER.value,
        server_default=text("'member'"),
    )
    invited_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invitation_token: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    invitation_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=InvitationStatus.ACCEPTED.value,
        server_default=text("'accepted'"),
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="members"
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="ck_org_members_role",
        ),
        CheckConstraint(
            "invitation_status IN ('pending', 'accepted', 'declined')",
            name="ck_org_members_invitation_status",
        ),
        Index(
            "uq_org_members_org_user",
            "organization_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index("ix_org_members_user_id", "user_id"),
        Index("ix_org_members_invited_email", "invited_email"),
    )
