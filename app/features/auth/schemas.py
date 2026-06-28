"""Pydantic request/response schemas for the auth feature."""

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.shared.base_schemas import ORMSchema

# Minimum password length enforced at registration and reset.
MIN_PASSWORD_LENGTH = 8


class RegisterRequest(BaseModel):
    """Payload for creating a new account."""

    email: EmailStr
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=128)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)


class LoginRequest(BaseModel):
    """Payload for authenticating with email and password."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """Access + refresh token pair returned on login/refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Payload carrying a refresh token to exchange for a new token pair."""

    refresh_token: str = Field(..., min_length=1)


class VerifyEmailRequest(BaseModel):
    """Payload carrying an email-verification token."""

    token: str = Field(..., min_length=1)


class ForgotPasswordRequest(BaseModel):
    """Payload requesting a password-reset email."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Payload carrying a reset token and the new password."""

    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=128)


class LogoutRequest(BaseModel):
    """Payload carrying the refresh token to revoke on logout."""

    refresh_token: str = Field(..., min_length=1)


class MessageResponse(BaseModel):
    """Generic success message envelope."""

    message: str


class UserRead(ORMSchema):
    """Public representation of a user account."""

    id: uuid.UUID
    email: EmailStr
    role: str
    is_active: bool
    is_verified: bool
