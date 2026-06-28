"""Database operations for users and profiles."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.features.users.models import User, UserProfile


async def get_user_with_profile(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Return a user with the profile relationship eagerly loaded, or ``None``."""
    result = await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.profile))
    )
    return result.scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    """Return a user by email, or ``None``."""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def update_profile(
    db: AsyncSession, profile: UserProfile, fields: dict
) -> UserProfile:
    """Apply the given non-null fields to a profile and persist."""
    for key, value in fields.items():
        setattr(profile, key, value)
    await db.commit()
    await db.refresh(profile)
    return profile


async def set_avatar_url(
    db: AsyncSession, profile: UserProfile, avatar_url: str
) -> UserProfile:
    """Persist a new avatar URL on the profile."""
    profile.avatar_url = avatar_url
    await db.commit()
    await db.refresh(profile)
    return profile


async def set_fcm_token(
    db: AsyncSession, profile: UserProfile, fcm_token: str
) -> UserProfile:
    """Persist a Firebase Cloud Messaging device token (used in Phase 7)."""
    profile.fcm_token = fcm_token
    await db.commit()
    await db.refresh(profile)
    return profile


async def update_role(db: AsyncSession, user: User, role: str) -> User:
    """Update a user's platform role (used by admin flows in Phase 8)."""
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user
