"""Tests for recommendations: personalized feed and similar events."""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

RECS_URL = "/api/v1/recommendations"
CATEGORIES_URL = "/api/v1/categories"
ORGS_URL = "/api/v1/organizations"
EVENTS_URL = "/api/v1/events"
ORDERS_URL = "/api/v1/orders"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


async def _make_category(client, admin, auth_headers, name: str) -> str:
    """Create a category as an admin and return its id."""
    resp = await client.post(
        CATEGORIES_URL, headers=auth_headers(admin), json={"name": name}
    )
    return resp.json()["id"]


async def _make_org(client, organizer, auth_headers, name: str) -> str:
    """Create an organization and return its id."""
    resp = await client.post(
        ORGS_URL,
        headers=auth_headers(organizer),
        json={"name": name, "contact_email": "o@example.com"},
    )
    return resp.json()["id"]


async def _published_event(
    client, organizer, auth_headers, org_id, *, category_id, city, price="10.00"
) -> tuple[str, str]:
    """Create + publish an event with a ticket tier; return (event_id, tier_id)."""
    event = (
        await client.post(
            EVENTS_URL,
            headers=auth_headers(organizer),
            json={
                "organization_id": org_id,
                "title": f"Event {city}",
                "description": "d",
                "venue_name": "v",
                "city": city,
                "category_id": category_id,
                "start_datetime": START,
                "end_datetime": END,
            },
        )
    ).json()
    tier = (
        await client.post(
            f"{EVENTS_URL}/{event['id']}/ticket-types",
            headers=auth_headers(organizer),
            json={"name": "GA", "price": price, "quantity_total": 50},
        )
    ).json()
    await client.post(
        f"{EVENTS_URL}/{event['id']}/publish", headers=auth_headers(organizer)
    )
    return event["id"], tier["id"]


async def _attend(client, db_session, buyer, auth_headers, event_id, tier_id) -> None:
    """Place + confirm an order so the buyer becomes an attendee of the event."""
    from app.features.attendees import services as att_services
    from app.features.orders.crud import get_order
    from app.features.users.crud import get_user_with_profile
    from app.shared.enums import OrderStatus

    order = (
        await client.post(
            ORDERS_URL,
            headers=auth_headers(buyer),
            json={
                "event_id": event_id,
                "items": [{"ticket_type_id": tier_id, "quantity": 1}],
            },
        )
    ).json()
    order_obj = await get_order(db_session, uuid.UUID(order["id"]))
    order_obj.status = OrderStatus.CONFIRMED.value
    order_obj.confirmed_at = datetime.now(UTC)
    buyer_obj = await get_user_with_profile(db_session, buyer.id)
    await att_services.generate_attendees_for_order(db_session, order_obj, buyer_obj)
    await db_session.commit()


# --------------------------------------------------------------------------- #
# personalized
# --------------------------------------------------------------------------- #


async def test_personalized_prefers_matching_category_and_city(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A matching-category/city event ranks first; attended events are excluded."""
    admin = await make_user(email="admin@example.com", role="admin")
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")

    cat_music = await _make_category(client, admin, auth_headers, "Music")
    cat_tech = await _make_category(client, admin, auth_headers, "Tech")
    org_id = await _make_org(client, organizer, auth_headers, "Rec Org")

    # History: buyer attended a Music event in Pune.
    attended_id, attended_tier = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat_music, city="Pune"
    )
    await _attend(client, db_session, buyer, auth_headers, attended_id, attended_tier)

    # Candidate B matches preferences; candidate D does not.
    match_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat_music, city="Pune"
    )
    other_id, _ = await _published_event(
        client,
        organizer,
        auth_headers,
        org_id,
        category_id=cat_tech,
        city="Delhi",
        price="999.00",
    )

    resp = await client.get(f"{RECS_URL}/events", headers=auth_headers(buyer))
    assert resp.status_code == 200
    body = resp.json()
    ids = [r["event"]["id"] for r in body]
    assert attended_id not in ids  # already attended
    assert body[0]["event"]["id"] == match_id
    assert body[0]["score"] == 0.65  # 0.3 category + 0.2 city + 0.15 price
    # The non-matching event is present but ranked lower.
    assert other_id in ids
    assert body[-1]["event"]["id"] == other_id


async def test_personalized_requires_auth(client: AsyncClient) -> None:
    """Personalized recommendations require authentication."""
    resp = await client.get(f"{RECS_URL}/events")
    assert resp.status_code == 401


async def test_personalized_respects_limit(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """The limit query parameter caps the number of recommendations."""
    admin = await make_user(email="admin2@example.com", role="admin")
    organizer = await make_user(email="org2@example.com")
    buyer = await make_user(email="buyer2@example.com")
    cat = await _make_category(client, admin, auth_headers, "Arts")
    org_id = await _make_org(client, organizer, auth_headers, "Rec Org2")
    for i in range(3):
        await _published_event(
            client, organizer, auth_headers, org_id, category_id=cat, city=f"C{i}"
        )

    resp = await client.get(f"{RECS_URL}/events?limit=1", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_personalized_limit_validation(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An out-of-range limit is rejected with 422."""
    resp = await client.get(
        f"{RECS_URL}/events?limit=0", headers=auth_headers(verified_user)
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# similar
# --------------------------------------------------------------------------- #


async def test_similar_events_public(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Similar events are public and rank a same-category event first."""
    admin = await make_user(email="admin3@example.com", role="admin")
    organizer = await make_user(email="org3@example.com")
    cat_music = await _make_category(client, admin, auth_headers, "Jazz")
    cat_tech = await _make_category(client, admin, auth_headers, "Code")
    org_id = await _make_org(client, organizer, auth_headers, "Rec Org3")

    source_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat_music, city="Pune"
    )
    similar_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat_music, city="Pune"
    )
    unrelated_id, _ = await _published_event(
        client,
        organizer,
        auth_headers,
        org_id,
        category_id=cat_tech,
        city="Delhi",
        price="999.00",
    )

    # No auth header — endpoint is public.
    resp = await client.get(f"{RECS_URL}/events/{source_id}/similar")
    assert resp.status_code == 200
    body = resp.json()
    ids = [r["event"]["id"] for r in body]
    assert source_id not in ids
    assert body[0]["event"]["id"] == similar_id
    assert unrelated_id in ids


async def test_similar_unknown_event_404(client: AsyncClient) -> None:
    """Similar events for an unknown event returns 404."""
    resp = await client.get(f"{RECS_URL}/events/{uuid.uuid4()}/similar")
    assert resp.status_code == 404
