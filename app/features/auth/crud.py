"""Database operations for authentication and account records."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.users.models import User, UserProfile


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Return the user with the given email, or ``None``."""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_verification_token(db: AsyncSession, token: str) -> User | None:
    """Return the user holding the given verification token, or ``None``."""
    result = await db.execute(select(User).where(User.verification_token == token))
    return result.scalar_one_or_none()


async def get_user_by_reset_token(db: AsyncSession, token: str) -> User | None:
    """Return the user holding the given password-reset token, or ``None``."""
    result = await db.execute(select(User).where(User.password_reset_token == token))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password_hash: str,
    first_name: str,
    last_name: str,
    verification_token: str,
    role: str,
) -> User:
    """Create a ``User`` and its linked ``UserProfile`` in one transaction."""
    user = User(
        email=email,
        password_hash=password_hash,
        role=role,
        is_verified=False,
        verification_token=verification_token,
        profile=UserProfile(first_name=first_name, last_name=last_name),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def mark_verified(db: AsyncSession, user: User) -> User:
    """Flag the user as verified and clear the verification token."""
    user.is_verified = True
    user.verification_token = None
    await db.commit()
    await db.refresh(user)
    return user


async def set_reset_token(
    db: AsyncSession, user: User, token: str, expires_at: datetime
) -> User:
    """Store a password-reset token and its expiry on the user."""
    user.password_reset_token = token
    user.password_reset_expires = expires_at
    await db.commit()
    await db.refresh(user)
    return user


async def update_password(db: AsyncSession, user: User, password_hash: str) -> User:
    """Set a new password hash and clear any reset token/expiry."""
    user.password_hash = password_hash
    user.password_reset_token = None
    user.password_reset_expires = None
    await db.commit()
    await db.refresh(user)
    return user


async def update_last_login(db: AsyncSession, user: User, when: datetime) -> User:
    """Record the timestamp of a successful login."""
    user.last_login_at = when
    await db.commit()
    await db.refresh(user)
    return user
