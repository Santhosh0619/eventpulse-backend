"""Media endpoints: upload, list, delete, and reorder event media."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.core.config import settings
from app.core.dependencies import DBSession, get_current_user
from app.core.exceptions import BadRequestError
from app.features.media import services
from app.features.media.models import EventMedia
from app.features.media.schemas import (
    MediaRead,
    MediaUploadResponse,
    ReorderRequest,
)
from app.features.users.models import User

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "/events/{event_id}/media",
    response_model=MediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload event media",
)
async def upload_media(
    event_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
    file: Annotated[UploadFile, File(...)],
    caption: Annotated[str | None, Form()] = None,
) -> EventMedia:
    """Upload an image or video to an event's gallery (org member only)."""
    if file.size is not None and file.size > settings.max_upload_size_bytes:
        raise BadRequestError(
            f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE_MB} MB"
        )
    content = await file.read()
    return await services.upload_event_media(
        db,
        event_id,
        current_user,
        content=content,
        content_type=file.content_type,
        filename=file.filename or "media",
        caption=caption,
    )


@router.get(
    "/events/{event_id}/media",
    response_model=list[MediaRead],
    summary="List event media",
)
async def list_media(event_id: uuid.UUID, db: DBSession) -> list[EventMedia]:
    """List an event's media in display order (public)."""
    return await services.list_media(db, event_id)


@router.put(
    "/events/{event_id}/media/reorder",
    response_model=list[MediaRead],
    summary="Reorder event media",
)
async def reorder_media(
    event_id: uuid.UUID,
    payload: ReorderRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> list[EventMedia]:
    """Reorder an event's media (org member only)."""
    return await services.reorder(db, event_id, current_user, payload.media_ids)


@router.delete(
    "/events/{event_id}/media/{media_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete event media",
)
async def delete_media(
    event_id: uuid.UUID,
    media_id: uuid.UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> None:
    """Delete a media item from an event (org member only)."""
    await services.delete_media(db, event_id, media_id, current_user)
