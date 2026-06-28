"""Tests for notifications: endpoints, fcm-token, triggers, reminders."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

NOTIF_URL = "/api/v1/notifications"
ORGS_URL = "/api/v1/organizations"
EVENTS_URL = "/api/v1/events"
ORDERS_URL = "/api/v1/orders"
REVIEWS_URL = "/api/v1/reviews"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


async def _make_notification(db_session, user_id, type_="generic", title="Hi"):
    """Create a notification via the service layer."""
    from app.features.notifications import services

    return await services.send_notification(
        db_session, user_id=user_id, type=type_, title=title, message="body"
    )


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #


async def test_list_and_unread_count(
    client: AsyncClient, verified_user, auth_headers, db_session: AsyncSession
) -> None:
    """Listing returns the user's notifications and unread-count reflects them."""
    await _make_notification(db_session, verified_user.id)
    await _make_notification(db_session, verified_user.id)

    listing = await client.get(NOTIF_URL, headers=auth_headers(verified_user))
    assert listing.status_code == 200
    assert len(listing.json()) == 2

    count = await client.get(
        f"{NOTIF_URL}/unread-count", headers=auth_headers(verified_user)
    )
    assert count.json()["unread"] == 2


async def test_list_requires_auth(client: AsyncClient) -> None:
    """Listing notifications without auth returns 401."""
    resp = await client.get(NOTIF_URL)
    assert resp.status_code == 401


async def test_mark_read(
    client: AsyncClient, verified_user, auth_headers, db_session: AsyncSession
) -> None:
    """Marking a notification read flips its flag and lowers the unread count."""
    notif = await _make_notification(db_session, verified_user.id)
    resp = await client.put(
        f"{NOTIF_URL}/{notif.id}/read", headers=auth_headers(verified_user)
    )
    assert resp.status_code == 200
    assert resp.json()["is_read"] is True

    count = await client.get(
        f"{NOTIF_URL}/unread-count", headers=auth_headers(verified_user)
    )
    assert count.json()["unread"] == 0


async def test_mark_read_non_owner_returns_403(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A user cannot mark someone else's notification read."""
    owner = await make_user(email="owner@example.com")
    other = await make_user(email="other@example.com")
    notif = await _make_notification(db_session, owner.id)
    resp = await client.put(
        f"{NOTIF_URL}/{notif.id}/read", headers=auth_headers(other)
    )
    assert resp.status_code == 403


async def test_mark_read_not_found_returns_404(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Marking an unknown notification read returns 404."""
    resp = await client.put(
        f"{NOTIF_URL}/{uuid.uuid4()}/read", headers=auth_headers(verified_user)
    )
    assert resp.status_code == 404


async def test_mark_all_read(
    client: AsyncClient, verified_user, auth_headers, db_session: AsyncSession
) -> None:
    """Mark-all-read clears the unread count."""
    await _make_notification(db_session, verified_user.id)
    await _make_notification(db_session, verified_user.id)
    resp = await client.put(
        f"{NOTIF_URL}/read-all", headers=auth_headers(verified_user)
    )
    assert resp.status_code == 200
    count = await client.get(
        f"{NOTIF_URL}/unread-count", headers=auth_headers(verified_user)
    )
    assert count.json()["unread"] == 0


# --------------------------------------------------------------------------- #
# fcm token
# --------------------------------------------------------------------------- #


async def test_update_fcm_token(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Registering an FCM token succeeds for an authenticated user."""
    resp = await client.put(
        "/api/v1/users/me/fcm-token",
        headers=auth_headers(verified_user),
        json={"fcm_token": "device-token-abc"},
    )
    assert resp.status_code == 200


async def test_update_fcm_token_requires_auth(client: AsyncClient) -> None:
    """Registering an FCM token without auth returns 401."""
    resp = await client.put(
        "/api/v1/users/me/fcm-token", json={"fcm_token": "x"}
    )
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# triggers
# --------------------------------------------------------------------------- #


async def test_review_reply_triggers_notification(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """An organizer response notifies the reviewer."""
    from app.features.attendees import services as att_services
    from app.features.attendees.crud import list_for_event
    from app.features.orders.crud import get_order
    from app.features.users.crud import get_user_with_profile

    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")

    org = (
        await client.post(
            ORGS_URL,
            headers=auth_headers(organizer),
            json={"name": "N Org", "contact_email": "o@example.com"},
        )
    ).json()
    event = (
        await client.post(
            EVENTS_URL,
            headers=auth_headers(organizer),
            json={
                "organization_id": org["id"],
                "title": "N Event",
                "description": "d",
                "venue_name": "v",
                "start_datetime": START,
                "end_datetime": END,
            },
        )
    ).json()
    tier = (
        await client.post(
            f"{EVENTS_URL}/{event['id']}/ticket-types",
            headers=auth_headers(organizer),
            json={"name": "GA", "price": "10.00", "quantity_total": 10},
        )
    ).json()
    await client.post(
        f"{EVENTS_URL}/{event['id']}/publish", headers=auth_headers(organizer)
    )
    order = (
        await client.post(
            ORDERS_URL,
            headers=auth_headers(buyer),
            json={"event_id": event["id"], "items": [{"ticket_type_id": tier["id"], "quantity": 1}]},
        )
    ).json()
    order_obj = await get_order(db_session, uuid.UUID(order["id"]))
    buyer_obj = await get_user_with_profile(db_session, buyer.id)
    await att_services.generate_attendees_for_order(db_session, order_obj, buyer_obj)
    await db_session.commit()
    attendees = await list_for_event(db_session, uuid.UUID(event["id"]))
    await client.post(
        "/api/v1/attendees/check-in",
        headers=auth_headers(organizer),
        json={"ticket_code": attendees[0].ticket_code},
    )
    review = (
        await client.post(
            f"{EVENTS_URL}/{event['id']}/reviews",
            headers=auth_headers(buyer),
            json={"rating": 5},
        )
    ).json()
    await client.post(
        f"{REVIEWS_URL}/{review['id']}/response",
        headers=auth_headers(organizer),
        json={"response": "Thank you!"},
    )

    notifs = await client.get(NOTIF_URL, headers=auth_headers(buyer))
    types = {n["type"] for n in notifs.json()}
    assert "review_reply" in types


async def test_dispatch_event_reminders(
    db_session: AsyncSession, make_user
) -> None:
    """The reminder job notifies attendees of events starting within 24h."""
    from app.features.attendees.models import Attendee
    from app.features.events.models import Event
    from app.features.notifications import services
    from app.features.organizations.models import Organization

    attendee_user = await make_user(email="att@example.com")
    org = Organization(
        name="Rem Org", slug=f"rem-{uuid.uuid4().hex[:8]}", contact_email="o@e.com"
    )
    db_session.add(org)
    await db_session.commit()
    event = Event(
        organization_id=org.id,
        title="Soon Event",
        slug=f"soon-{uuid.uuid4().hex[:8]}",
        description="d",
        venue_name="v",
        start_datetime=datetime.now(UTC) + timedelta(hours=12),
        end_datetime=datetime.now(UTC) + timedelta(hours=14),
        status="published",
    )
    db_session.add(event)
    await db_session.commit()
    db_session.add(
        Attendee(
            event_id=event.id,
            user_id=attendee_user.id,
            ticket_code=f"EP-ATT-{uuid.uuid4().hex[:8]}",
            first_name="A",
            last_name="B",
            email=attendee_user.email,
        )
    )
    await db_session.commit()

    sent = await services.dispatch_event_reminders(db_session)
    assert sent >= 1
    notifs = await services.list_notifications(db_session, attendee_user)
    assert any(n.type == "event_reminder" for n in notifs)
