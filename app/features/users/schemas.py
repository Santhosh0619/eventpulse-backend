"""Pydantic schemas for the users feature (profiles & account info)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.shared.base_schemas import ORMSchema


class ProfileRead(ORMSchema):
    """Full profile representation returned to the profile owner."""

    first_name: str
    last_name: str
    phone: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    date_of_birth: date | None = None
    city: str | None = None
    country: str | None = None
    preferences: dict = Field(default_factory=dict)


class ProfileUpdate(BaseModel):
    """Editable profile fields. All optional; only provided fields are updated."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    bio: str | None = None
    date_of_birth: date | None = None
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    preferences: dict | None = None


class UserRead(ORMSchema):
    """Authenticated user's own account, including their profile."""

    id: uuid.UUID
    email: EmailStr
    role: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    profile: ProfileRead | None = None


class PublicProfile(ORMSchema):
    """Public subset of a profile (no phone / DOB / preferences)."""

    first_name: str
    last_name: str
    avatar_url: str | None = None
    bio: str | None = None
    city: str | None = None
    country: str | None = None


class PublicUserRead(ORMSchema):
    """Public representation of any user (no email or account flags)."""

    id: uuid.UUID
    role: str
    profile: PublicProfile | None = None


class AvatarUploadResponse(BaseModel):
    """Response returned after a successful avatar upload."""

    avatar_url: str


class FcmTokenRequest(BaseModel):
    """Payload for registering a device's FCM push token."""

    # FCM registration tokens are opaque and contain no whitespace; reject
    # malformed values rather than storing garbage that can never deliver.
    fcm_token: str = Field(..., min_length=1, max_length=500, pattern=r"^\S+$")


class MessageResponse(BaseModel):
    """Generic success message."""

    message: str
