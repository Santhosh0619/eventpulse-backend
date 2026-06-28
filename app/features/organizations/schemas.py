"""Pydantic schemas for the organizations feature."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.shared.base_schemas import ORMSchema
from app.shared.enums import OrgMemberRole


class OrgCreate(BaseModel):
    """Payload for creating an organization."""

    name: str = Field(..., min_length=1, max_length=200)
    contact_email: EmailStr
    description: str | None = None
    website: str | None = Field(default=None, max_length=500)
    logo_url: str | None = Field(default=None, max_length=500)


class OrgUpdate(BaseModel):
    """Editable organization fields (all optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_email: EmailStr | None = None
    description: str | None = None
    website: str | None = Field(default=None, max_length=500)
    logo_url: str | None = Field(default=None, max_length=500)


class OrgRead(ORMSchema):
    """Organization representation."""

    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    logo_url: str | None = None
    website: str | None = None
    contact_email: EmailStr
    is_verified: bool
    created_by: uuid.UUID | None = None
    created_at: datetime


class OrgWithRole(OrgRead):
    """Organization plus the requesting user's role within it."""

    my_role: str


class MemberRead(ORMSchema):
    """Membership record representation."""

    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID | None = None
    role: str
    invited_email: str | None = None
    invitation_status: str
    joined_at: datetime | None = None


class InviteRequest(BaseModel):
    """Payload for inviting a member by email."""

    email: EmailStr
    role: OrgMemberRole = OrgMemberRole.MEMBER


class InviteResponse(BaseModel):
    """Response after creating an invitation."""

    id: uuid.UUID
    invited_email: str
    role: str
    invitation_status: str
    invitation_token: str


class MemberRoleUpdate(BaseModel):
    """Payload for changing a member's role."""

    role: OrgMemberRole


class MessageResponse(BaseModel):
    """Generic success message envelope."""

    message: str
