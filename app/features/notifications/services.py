"""Business logic for notifications and multi-channel dispatch."""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError
from app.features.notifications import crud
from app.features.notifications.models import Notification
from app.features.users.models import User
from app.shared.enums import NotificationChannel
from app.utils import email as email_utils

logger = logging.getLogger("eventpulse.notifications")

_firebase_app = None


def _get_firebase_app():
    """Lazily initialize and return the Firebase app, or ``None`` if unavailable."""
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app
    try:
        import firebase_admin
        from firebase_admin import credentials

        cred = credentials.Certificate(json.loads(settings.FIREBASE_CREDENTIALS_JSON))
        _firebase_app = firebase_admin.initialize_app(cred)
    except Exception:  # noqa: BLE001 - push is best-effort
        logger.warning("Firebase not configured; push notifications disabled")
        _firebase_app = None
    return _firebase_app


async def _send_push(fcm_token: str, title: str, message: str, data: dict) -> None:
    """Best-effort FCM push; failures are logged, never raised."""
    try:
        app = _get_firebase_app()
        if app is None:
            return
        from firebase_admin import messaging

        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=message),
            data={k: str(v) for k, v in (data or {}).items()},
            token=fcm_token,
        )
        messaging.send(msg, app=app)
    except Exception:  # noqa: BLE001 - push is best-effort
        logger.exception("Failed to send push notification")


async def send_notification(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    type: str,
    title: str,
    message: str,
    data: dict | None = None,
    channel: str = NotificationChannel.IN_APP.value,
) -> Notification:
    """Create a notification record and dispatch it to its channel.

    The in-app record is always persisted. Push/email delivery is best-effort and
    never raises, so notification failures cannot break the triggering action.
    """
    notification = await crud.create(
        db,
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        data=data or {},
        channel=channel,
    )

    if channel == NotificationChannel.PUSH.value:
        from app.features.users.crud import get_user_with_profile

        user = await get_user_with_profile(db, user_id)
        token = user.profile.fcm_token if user and user.profile else None
        if token:
            await _send_push(token, title, message, data or {})
    elif channel == NotificationChannel.EMAIL.value:
        from app.features.users.crud import get_user_with_profile

        user = await get_user_with_profile(db, user_id)
        if user:
            await email_utils.send_email(user.email, title, f"<p>{message}</p>")

    return notification


async def list_notifications(db: AsyncSession, user: User) -> list[Notification]:
    """Return the authenticated user's notifications."""
    return await crud.list_for_user(db, user.id)


async def get_unread_count(db: AsyncSession, user: User) -> int:
    """Return the count of unread notifications for the user."""
    return await crud.unread_count(db, user.id)


async def mark_read(
    db: AsyncSession, notification_id: uuid.UUID, user: User
) -> Notification:
    """Mark a notification read (must belong to the caller)."""
    notification = await crud.get(db, notification_id)
    if notification is None:
        raise NotFoundError("Notification not found")
    if notification.user_id != user.id:
        raise ForbiddenError("You do not have access to this notification")
    return await crud.mark_read(db, notification)


async def mark_all_read(db: AsyncSession, user: User) -> int:
    """Mark all of the caller's notifications as read."""
    return await crud.mark_all_read(db, user.id)


async def dispatch_event_reminders(db: AsyncSession) -> int:
    """Notify attendees of events starting in the next 24h. Returns count sent.

    Run daily by the scheduler. Queries are direct model reads (a cross-cutting
    background aggregation), then dispatch goes through ``send_notification``.
    """
    from app.features.attendees.models import Attendee
    from app.features.events.models import Event

    now = datetime.now(UTC)
    window_end = now + timedelta(hours=24)
    events = (
        (
            await db.execute(
                select(Event).where(
                    Event.status == "published",
                    Event.start_datetime >= now,
                    Event.start_datetime <= window_end,
                )
            )
        )
        .scalars()
        .all()
    )

    sent = 0
    for event in events:
        attendees = (
            (
                await db.execute(
                    select(Attendee.user_id)
                    .where(Attendee.event_id == event.id)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        for user_id in attendees:
            if user_id is None:
                continue
            await send_notification(
                db,
                user_id=user_id,
                type="event_reminder",
                title=f"Reminder: {event.title}",
                message=f"{event.title} starts soon.",
                data={"event_id": str(event.id), "screen": "event_detail"},
            )
            sent += 1
    return sent
