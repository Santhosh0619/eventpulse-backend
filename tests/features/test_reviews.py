"""Tests for the reviews feature: submit, list, summary, edit, respond, moderate."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

ORGS_URL = "/api/v1/organizations"
EVENTS_URL = "/api/v1/events"
ORDERS_URL = "/api/v1/orders"
REVIEWS_URL = "/api/v1/reviews"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


async def _attended_event(
    client: AsyncClient, organizer, buyer, auth_headers, db_session: AsyncSession
) -> str:
    """Set up an event where ``buyer`` has a checked-in attendee. Returns event id."""
    from app.features.attendees import services as att_services
    from app.features.attendees.crud import list_for_event
    from app.features.orders.crud import get_order
    from app.features.users.crud import get_user_with_profile

    org = (
        await client.post(
            ORGS_URL,
            headers=auth_headers(organizer),
            json={"name": "Rev Org", "contact_email": "o@example.com"},
        )
    ).json()
    event = (
        await client.post(
            EVENTS_URL,
            headers=auth_headers(organizer),
            json={
                "organization_id": org["id"],
                "title": "Rev Event",
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
            json={"name": "GA", "price": "10.00", "quantity_total": 50},
        )
    ).json()
    await client.post(
        f"{EVENTS_URL}/{event['id']}/publish", headers=auth_headers(organizer)
    )
    order = (
        await client.post(
            ORDERS_URL,
            headers=auth_headers(buyer),
            json={
                "event_id": event["id"],
                "items": [{"ticket_type_id": tier["id"], "quantity": 1}],
            },
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
    return event["id"]


# --------------------------------------------------------------------------- #
# submit
# --------------------------------------------------------------------------- #


async def test_submit_review_success(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A checked-in attendee can submit a review."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    resp = await client.post(
        f"{EVENTS_URL}/{event_id}/reviews",
        headers=auth_headers(buyer),
        json={"rating": 5, "title": "Great", "comment": "Loved it"},
    )
    assert resp.status_code == 201
    assert resp.json()["rating"] == 5


async def test_submit_review_not_attended_returns_403(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A user without a checked-in attendee cannot review."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    stranger = await make_user(email="stranger@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    resp = await client.post(
        f"{EVENTS_URL}/{event_id}/reviews",
        headers=auth_headers(stranger),
        json={"rating": 4},
    )
    assert resp.status_code == 403


async def test_submit_review_duplicate_returns_409(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A second review by the same user for the same event returns 409."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    await client.post(
        f"{EVENTS_URL}/{event_id}/reviews",
        headers=auth_headers(buyer),
        json={"rating": 5},
    )
    dup = await client.post(
        f"{EVENTS_URL}/{event_id}/reviews",
        headers=auth_headers(buyer),
        json={"rating": 3},
    )
    assert dup.status_code == 409


async def test_submit_review_invalid_rating_returns_422(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A rating outside 1-5 is rejected with 422."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    resp = await client.post(
        f"{EVENTS_URL}/{event_id}/reviews",
        headers=auth_headers(buyer),
        json={"rating": 7},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# list / summary
# --------------------------------------------------------------------------- #


async def test_list_and_summary(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Listing and summary reflect submitted reviews."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    await client.post(
        f"{EVENTS_URL}/{event_id}/reviews",
        headers=auth_headers(buyer),
        json={"rating": 4},
    )
    listing = await client.get(f"{EVENTS_URL}/{event_id}/reviews")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    summary = await client.get(f"{EVENTS_URL}/{event_id}/reviews/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["total_reviews"] == 1
    assert body["average_rating"] == 4.0
    assert body["distribution"]["4"] == 1


# --------------------------------------------------------------------------- #
# edit / respond / moderate
# --------------------------------------------------------------------------- #


async def _create_review(client, buyer, auth_headers, event_id) -> dict:
    return (
        await client.post(
            f"{EVENTS_URL}/{event_id}/reviews",
            headers=auth_headers(buyer),
            json={"rating": 3, "comment": "ok"},
        )
    ).json()


async def test_update_own_review_and_forbid_others(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Owners can edit their review; others cannot."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    other = await make_user(email="other@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    review = await _create_review(client, buyer, auth_headers, event_id)

    ok = await client.put(
        f"{REVIEWS_URL}/{review['id']}",
        headers=auth_headers(buyer),
        json={"rating": 5},
    )
    assert ok.status_code == 200
    assert ok.json()["rating"] == 5

    forbidden = await client.put(
        f"{REVIEWS_URL}/{review['id']}",
        headers=auth_headers(other),
        json={"rating": 1},
    )
    assert forbidden.status_code == 403


async def test_delete_own_review(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """An owner can delete their review."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    review = await _create_review(client, buyer, auth_headers, event_id)
    resp = await client.delete(
        f"{REVIEWS_URL}/{review['id']}", headers=auth_headers(buyer)
    )
    assert resp.status_code == 204


async def test_respond_to_review(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """An org member can respond to a review; a non-member cannot."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    review = await _create_review(client, buyer, auth_headers, event_id)

    ok = await client.post(
        f"{REVIEWS_URL}/{review['id']}/response",
        headers=auth_headers(organizer),
        json={"response": "Thanks for coming!"},
    )
    assert ok.status_code == 200
    assert ok.json()["organizer_response"] == "Thanks for coming!"

    forbidden = await client.post(
        f"{REVIEWS_URL}/{review['id']}/response",
        headers=auth_headers(buyer),
        json={"response": "nope"},
    )
    assert forbidden.status_code == 403


async def test_visibility_moderation_admin_only(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """An admin can hide a review, removing it from public listings."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    admin = await make_user(email="admin@example.com", role="admin")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    review = await _create_review(client, buyer, auth_headers, event_id)

    denied = await client.put(
        f"{REVIEWS_URL}/{review['id']}/visibility",
        headers=auth_headers(buyer),
        json={"is_visible": False},
    )
    assert denied.status_code == 403

    hidden = await client.put(
        f"{REVIEWS_URL}/{review['id']}/visibility",
        headers=auth_headers(admin),
        json={"is_visible": False},
    )
    assert hidden.status_code == 200

    listing = await client.get(f"{EVENTS_URL}/{event_id}/reviews")
    assert all(r["id"] != review["id"] for r in listing.json())
