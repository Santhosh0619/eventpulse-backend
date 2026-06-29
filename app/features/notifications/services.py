"""Business logic for notifications and multi-channel dispatch."""

import asyncio
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
from app.shared.enums import EventStatus, NotificationChannel, NotificationType
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
        # ``messaging.send`` is blocking network I/O; keep it off the event loop.
        await asyncio.to_thread(messaging.send, msg, app=app)
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
    commit: bool = True,
) -> Notification:
    """Create a notification record and dispatch it to its channel.

    The in-app record is always persisted. Push/email delivery is best-effort and
    never raises, so notification failures cannot break the triggering action.

    Pass ``commit=False`` when called from inside another feature's open
    transaction so the notification write stays atomic with the triggering action;
    the caller is then responsible for committing.
    """
    notification = await crud.create(
        db,
        commit=commit,
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
            # Render through the autoescaped Jinja2 template; never interpolate
            # the message into raw HTML (avoids injection in the email channel).
            html = email_utils.render_template(
                "notification.html", title=title, message=message
            )
            await email_utils.send_email(user.email, title, html)

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
                    Event.status == EventStatus.PUBLISHED.value,
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
        # Skip attendees already reminded for this event so a daily run whose
        # 24h window overlaps the previous run never double-notifies.
        already_notified = set(
            (
                await db.execute(
                    select(Notification.user_id).where(
                        Notification.type == NotificationType.EVENT_REMINDER.value,
                        Notification.data["event_id"].astext == str(event.id),
                    )
                )
            )
            .scalars()
            .all()
        )
        for user_id in attendees:
            if user_id is None or user_id in already_notified:
                continue
            await send_notification(
                db,
                user_id=user_id,
                type=NotificationType.EVENT_REMINDER.value,
                title=f"Reminder: {event.title}",
                message=f"{event.title} starts soon.",
                data={"event_id": str(event.id), "screen": "event_detail"},
                commit=False,
            )
            already_notified.add(user_id)
            sent += 1

    # One commit for the whole batch instead of one per attendee.
    if sent:
        await db.commit()
    return sent
