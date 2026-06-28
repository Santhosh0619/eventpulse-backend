"""Users endpoints: own profile read/update, public user lookup, avatar upload."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.core.config import settings
from app.core.dependencies import DBSession, get_current_user
from app.core.exceptions import BadRequestError
from app.features.users import services
from app.features.users.models import User
from app.features.users.schemas import (
    AvatarUploadResponse,
    FcmTokenRequest,
    MessageResponse,
    ProfileUpdate,
    PublicUserRead,
    UserRead,
)

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/me", response_model=UserRead, summary="Get my profile")
async def get_me(current_user: CurrentUser, db: DBSession) -> User:
    """Return the authenticated user's account and profile."""
    return await services.get_my_profile(db, current_user)


@router.put("/me", response_model=UserRead, summary="Update my profile")
async def update_me(
    payload: ProfileUpdate, current_user: CurrentUser, db: DBSession
) -> User:
    """Update the authenticated user's profile with the supplied fields."""
    fields = payload.model_dump(exclude_unset=True)
    return await services.update_my_profile(db, current_user, fields)


@router.put(
    "/me/avatar",
    response_model=AvatarUploadResponse,
    summary="Upload my avatar",
)
async def upload_avatar(
    current_user: CurrentUser,
    db: DBSession,
    file: Annotated[UploadFile, File(...)],
) -> AvatarUploadResponse:
    """Upload and set the authenticated user's avatar image."""
    # Reject oversized uploads before reading the whole body into memory.
    if file.size is not None and file.size > settings.max_upload_size_bytes:
        raise BadRequestError(
            f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE_MB} MB"
        )
    content = await file.read()
    url = await services.upload_avatar(
        db,
        current_user,
        content=content,
        content_type=file.content_type,
        filename=file.filename or "avatar",
    )
    return AvatarUploadResponse(avatar_url=url)


@router.put(
    "/me/fcm-token",
    response_model=MessageResponse,
    summary="Register FCM push token",
)
async def update_fcm_token(
    payload: FcmTokenRequest, current_user: CurrentUser, db: DBSession
) -> MessageResponse:
    """Register the device's FCM token for push notifications."""
    await services.update_fcm_token(db, current_user, payload.fcm_token)
    return MessageResponse(message="FCM token updated")


@router.get("/{user_id}", response_model=PublicUserRead, summary="Get a user")
async def get_user(user_id: uuid.UUID, db: DBSession) -> User:
    """Return the public profile of any active user."""
    return await services.get_public_user(db, user_id)
