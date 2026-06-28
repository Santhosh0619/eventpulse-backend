"""Business logic for the users feature."""

import uuid
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.features.users import crud
from app.features.users.models import User
from app.shared.storage import save_upload


async def get_my_profile(db: AsyncSession, user: User) -> User:
    """Return the authenticated user with their profile eagerly loaded."""
    full = await crud.get_user_with_profile(db, user.id)
    if full is None:
        raise NotFoundError("User not found")
    return full


async def update_my_profile(db: AsyncSession, user: User, fields: dict) -> User:
    """Update the authenticated user's profile with the provided fields."""
    full = await crud.get_user_with_profile(db, user.id)
    if full is None or full.profile is None:
        raise NotFoundError("Profile not found")
    if fields:
        await crud.update_profile(db, full.profile, fields)
    return full


async def get_public_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """Return a user's public-facing record, or raise 404."""
    user = await crud.get_user_with_profile(db, user_id)
    if user is None or not user.is_active:
        raise NotFoundError("User not found")
    return user


async def upload_avatar(
    db: AsyncSession,
    user: User,
    *,
    content: bytes,
    content_type: str | None,
    filename: str,
) -> str:
    """Validate and store an avatar image, returning its public URL.

    Raises:
        BadRequestError: If the file type is unsupported or the file is too large.
    """
    if content_type not in settings.allowed_image_types_list:
        raise BadRequestError(
            f"Unsupported file type. Allowed: {settings.ALLOWED_IMAGE_TYPES}"
        )
    if len(content) > settings.max_upload_size_bytes:
        raise BadRequestError(
            f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE_MB} MB"
        )
    # Verify the bytes are actually a valid image (defends against a spoofed
    # Content-Type header that claims image/* for a non-image payload).
    try:
        with Image.open(BytesIO(content)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise BadRequestError("File is not a valid image") from exc

    full = await crud.get_user_with_profile(db, user.id)
    if full is None or full.profile is None:
        raise NotFoundError("Profile not found")

    _relative, public_url = await save_upload(content, "avatars", filename)
    await crud.set_avatar_url(db, full.profile, public_url)
    return public_url


async def change_role(db: AsyncSession, user: User, role: str) -> User:
    """Change a user's platform role (consumed by admin flows in Phase 8)."""
    return await crud.update_role(db, user, role)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Look up a user by email (cross-feature helper for invitations/admin)."""
    return await crud.get_by_email(db, email)
