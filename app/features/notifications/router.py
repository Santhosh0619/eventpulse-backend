"""Notification endpoints: list, mark read, mark all read, unread count."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import DBSession, get_current_user
from app.features.notifications import services
from app.features.notifications.models import Notification
from app.features.notifications.schemas import (
    MessageResponse,
    NotificationRead,
    UnreadCountResponse,
)
from app.features.users.models import User

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=list[NotificationRead], summary="List notifications")
async def list_notifications(
    current_user: CurrentUser, db: DBSession
) -> list[Notification]:
    """Return the authenticated user's notifications, newest first."""
    return await services.list_notifications(db, current_user)


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="Unread notification count",
)
async def unread_count(current_user: CurrentUser, db: DBSession) -> UnreadCountResponse:
    """Return the count of unread notifications."""
    return UnreadCountResponse(unread=await services.get_unread_count(db, current_user))


@router.put("/read-all", response_model=MessageResponse, summary="Mark all read")
async def mark_all_read(current_user: CurrentUser, db: DBSession) -> MessageResponse:
    """Mark all of the caller's notifications as read."""
    count = await services.mark_all_read(db, current_user)
    return MessageResponse(message=f"Marked {count} notifications as read")


@router.put(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Mark a notification read",
)
async def mark_read(
    notification_id: uuid.UUID, current_user: CurrentUser, db: DBSession
) -> Notification:
    """Mark a single notification as read."""
    return await services.mark_read(db, notification_id, current_user)
