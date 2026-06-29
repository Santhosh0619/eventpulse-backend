"""Auth endpoints: register, login, token refresh, email/password flows, logout."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.core.config import settings
from app.core.dependencies import DBSession, get_current_user
from app.core.rate_limit import limiter
from app.features.auth import services
from app.features.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserRead,
    VerifyEmailRequest,
)
from app.features.users.models import User

router = APIRouter()


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def register(request: Request, payload: RegisterRequest, db: DBSession) -> User:
    """Create a new unverified account and email a verification link."""
    return await services.register(
        db,
        email=payload.email,
        password=payload.password,
        first_name=payload.first_name,
        last_name=payload.last_name,
    )


@router.post("/login", response_model=TokenResponse, summary="Log in")
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(
    request: Request, payload: LoginRequest, db: DBSession
) -> TokenResponse:
    """Authenticate with email and password, returning a token pair."""
    return await services.login(db, email=payload.email, password=payload.password)


@router.post("/refresh", response_model=TokenResponse, summary="Refresh tokens")
async def refresh(payload: RefreshRequest, db: DBSession) -> TokenResponse:
    """Exchange a valid refresh token for a new (rotated) token pair."""
    return await services.refresh_token(db, token=payload.refresh_token)


@router.post(
    "/verify-email", response_model=MessageResponse, summary="Verify email address"
)
async def verify_email(payload: VerifyEmailRequest, db: DBSession) -> MessageResponse:
    """Mark an account as verified using its verification token."""
    await services.verify_email(db, token=payload.token)
    return MessageResponse(message="Email verified successfully")


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request a password reset",
)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def forgot_password(
    request: Request, payload: ForgotPasswordRequest, db: DBSession
) -> MessageResponse:
    """Email a password-reset link if the account exists (always succeeds)."""
    await services.forgot_password(db, email=payload.email)
    return MessageResponse(
        message="If an account exists for this email, a reset link has been sent"
    )


@router.post(
    "/reset-password", response_model=MessageResponse, summary="Reset password"
)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def reset_password(
    request: Request, payload: ResetPasswordRequest, db: DBSession
) -> MessageResponse:
    """Set a new password using a valid, unexpired reset token."""
    await services.reset_password(
        db, token=payload.token, new_password=payload.new_password
    )
    return MessageResponse(message="Password reset successfully")


@router.post("/logout", response_model=MessageResponse, summary="Log out")
async def logout(
    payload: LogoutRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> MessageResponse:
    """Revoke the caller's own refresh token (requires a valid access token)."""
    await services.logout(
        token=payload.refresh_token, current_user_id=str(current_user.id)
    )
    return MessageResponse(message="Logged out successfully")
