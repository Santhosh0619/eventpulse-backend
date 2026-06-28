"""Business logic for authentication flows."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    UnauthorizedError,
)
from app.core.redis import blacklist_token, is_token_blacklisted
from app.core.security import (
    JWTError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.features.auth import crud
from app.features.auth.schemas import TokenResponse
from app.features.users.models import User
from app.shared.enums import UserRole
from app.utils import email as email_utils

# Lifetime of a password-reset token.
RESET_TOKEN_TTL = timedelta(hours=1)


def _issue_tokens(user: User) -> TokenResponse:
    """Create an access + refresh token pair for the given user."""
    subject = str(user.id)
    claims = {"role": user.role}
    return TokenResponse(
        access_token=create_access_token(subject, extra_claims=claims),
        refresh_token=create_refresh_token(subject, extra_claims=claims),
    )


def _remaining_ttl_seconds(payload: dict) -> int:
    """Return the number of seconds until a token's ``exp`` claim, floored at 0."""
    exp = payload.get("exp")
    if exp is None:
        return 0
    remaining = int(exp - datetime.now(UTC).timestamp())
    return max(remaining, 0)


async def register(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
) -> User:
    """Register a new (unverified) account and send a verification email.

    Raises:
        ConflictError: If the email is already registered.
    """
    existing = await crud.get_user_by_email(db, email)
    if existing is not None:
        raise ConflictError("An account with this email already exists")

    verification_token = secrets.token_urlsafe(32)
    user = await crud.create_user(
        db,
        email=email,
        password_hash=hash_password(password),
        first_name=first_name,
        last_name=last_name,
        verification_token=verification_token,
        role=UserRole.ATTENDEE.value,
    )

    await email_utils.send_verification_email(user.email, verification_token)
    return user


async def login(db: AsyncSession, *, email: str, password: str) -> TokenResponse:
    """Authenticate a user and return a token pair.

    Raises:
        UnauthorizedError: On unknown email or wrong password.
        ForbiddenError: If the account is inactive or unverified.
    """
    user = await crud.get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid email or password")
    if not user.is_active:
        raise ForbiddenError("This account has been deactivated")
    if not user.is_verified:
        raise ForbiddenError("Please verify your email before logging in")

    await crud.update_last_login(db, user, datetime.now(UTC))
    return _issue_tokens(user)


async def refresh_token(db: AsyncSession, *, token: str) -> TokenResponse:
    """Validate a refresh token, rotate it, and return a new token pair.

    Raises:
        UnauthorizedError: If the token is invalid, expired, of the wrong type,
            blacklisted, or its user no longer exists / is inactive.
    """
    try:
        payload = decode_token(token)
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired refresh token") from exc

    if payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid token type")

    jti = payload.get("jti")
    if jti and await is_token_blacklisted(jti):
        raise UnauthorizedError("Refresh token has been revoked")

    user_id = payload.get("sub")
    try:
        user_pk = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError) as exc:
        raise UnauthorizedError("Invalid token payload") from exc

    user = await db.get(User, user_pk) if user_pk else None
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive")

    # Rotate: revoke the presented refresh token for its remaining lifetime.
    if jti:
        await blacklist_token(jti, _remaining_ttl_seconds(payload))

    return _issue_tokens(user)


async def verify_email(db: AsyncSession, *, token: str) -> None:
    """Mark the account owning ``token`` as verified.

    Raises:
        BadRequestError: If the token does not match any account.
    """
    user = await crud.get_user_by_verification_token(db, token)
    if user is None:
        raise BadRequestError("Invalid or expired verification token")
    await crud.mark_verified(db, user)


async def forgot_password(db: AsyncSession, *, email: str) -> None:
    """Issue a password-reset token and email it, if the account exists.

    Always succeeds silently to avoid leaking which emails are registered.
    """
    user = await crud.get_user_by_email(db, email)
    if user is None or not user.is_active:
        return

    reset_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + RESET_TOKEN_TTL
    await crud.set_reset_token(db, user, reset_token, expires_at)
    await email_utils.send_password_reset_email(user.email, reset_token)


async def reset_password(db: AsyncSession, *, token: str, new_password: str) -> None:
    """Reset a user's password using a valid, unexpired reset token.

    Raises:
        BadRequestError: If the token is unknown or expired.
    """
    user = await crud.get_user_by_reset_token(db, token)
    if user is None:
        raise BadRequestError("Invalid or expired reset token")

    expires = user.password_reset_expires
    if expires is None or expires < datetime.now(UTC):
        raise BadRequestError("Invalid or expired reset token")

    await crud.update_password(db, user, hash_password(new_password))


async def logout(*, token: str, current_user_id: str) -> None:
    """Revoke the caller's own refresh token by blacklisting its JTI.

    Only revokes the token if it belongs to ``current_user_id``; a token for a
    different user is ignored, preventing cross-user revocation. Invalid tokens
    are ignored too, so logout is always idempotent.
    """
    try:
        payload = decode_token(token)
    except JWTError:
        return

    if payload.get("sub") != current_user_id:
        return

    jti = payload.get("jti")
    if jti:
        await blacklist_token(jti, _remaining_ttl_seconds(payload))
