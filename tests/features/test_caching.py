"""Tests for Redis caching: cache utility, cache hits, and write invalidation."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

EVENTS_URL = "/api/v1/events"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


async def _published_event(client, organizer, auth_headers, *, city="Cacheville"):
    """Create + publish an event with a tier; return (event_id, tier_id)."""
    org = (
        await client.post(
            "/api/v1/organizations",
            headers=auth_headers(organizer),
            json={"name": "Cache Org", "contact_email": "o@example.com"},
        )
    ).json()
    event = (
        await client.post(
            EVENTS_URL,
            headers=auth_headers(organizer),
            json={
                "organization_id": org["id"],
                "title": "Cache Event",
                "description": "d",
                "venue_name": "v",
                "city": city,
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
    return event["id"], tier["id"]


# --------------------------------------------------------------------------- #
# cache utility
# --------------------------------------------------------------------------- #


async def test_cache_roundtrip_and_prefix_invalidation() -> None:
    """set_json/get_json round-trip and invalidate_prefix clears matching keys."""
    from app.core import cache

    await cache.set_json("test:cache:a", {"v": 1}, ttl=60)
    await cache.set_json("test:cache:b", {"v": 2}, ttl=60)
    assert await cache.get_json("test:cache:a") == {"v": 1}

    await cache.invalidate_prefix("test:cache:")
    assert await cache.get_json("test:cache:a") is None
    assert await cache.get_json("test:cache:b") is None


async def test_get_json_miss_returns_none() -> None:
    """A missing key returns None rather than raising."""
    from app.core import cache

    assert await cache.get_json(f"test:absent:{uuid.uuid4()}") is None


# --------------------------------------------------------------------------- #
# availability: cache hit then invalidation
# --------------------------------------------------------------------------- #


async def test_availability_served_from_cache_then_invalidated(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Availability is cached (stale read proves a hit); tier writes invalidate it."""
    from app.features.tickets.crud import get_ticket_type

    organizer = await make_user(email="org@example.com")
    event_id, tier_id = await _published_event(client, organizer, auth_headers)

    # First read populates the cache.
    first = await client.get(f"{EVENTS_URL}/{event_id}/availability")
    assert first.json()["tiers"][0]["quantity_sold"] == 0

    # Mutate the DB directly, bypassing the service's invalidation.
    tier = await get_ticket_type(db_session, uuid.UUID(tier_id))
    tier.quantity_sold = 5
    await db_session.commit()

    # The stale cached value is still served — proves the read hit the cache.
    cached = await client.get(f"{EVENTS_URL}/{event_id}/availability")
    assert cached.json()["tiers"][0]["quantity_sold"] == 0

    # A tier update through the service invalidates the cache.
    await client.put(
        f"{EVENTS_URL}/{event_id}/ticket-types/{tier_id}",
        headers=auth_headers(organizer),
        json={"name": "General"},
    )
    fresh = await client.get(f"{EVENTS_URL}/{event_id}/availability")
    assert fresh.json()["tiers"][0]["quantity_sold"] == 5


# --------------------------------------------------------------------------- #
# event listings: invalidation on publish
# --------------------------------------------------------------------------- #


async def test_event_listing_invalidated_on_publish(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Publishing a new event invalidates cached listings filtered by its city."""
    organizer = await make_user(email="org2@example.com")
    city = f"City-{uuid.uuid4().hex[:8]}"

    # Prime the cache for this city's listing (currently empty).
    first = await client.get(f"{EVENTS_URL}?city={city}")
    assert first.json()["total"] == 0

    await _published_event(client, organizer, auth_headers, city=city)

    # The publish invalidated the listing cache, so the new event appears.
    second = await client.get(f"{EVENTS_URL}?city={city}")
    assert second.json()["total"] == 1
    assert second.json()["items"][0]["city"] == city


# --------------------------------------------------------------------------- #
# review summary: cache hit preserves int-keyed distribution
# --------------------------------------------------------------------------- #


async def test_review_summary_cached_with_int_distribution(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Summary cache hit preserves the int-keyed rating distribution."""
    from app.features.attendees import services as att_services
    from app.features.attendees.crud import list_for_event
    from app.features.orders.crud import get_order
    from app.features.users.crud import get_user_with_profile
    from app.shared.enums import OrderStatus

    organizer = await make_user(email="org3@example.com")
    buyer = await make_user(email="buyer3@example.com")
    event_id, tier_id = await _published_event(client, organizer, auth_headers)

    # Confirm an order and check the buyer in so they can review.
    order = (
        await client.post(
            "/api/v1/orders",
            headers=auth_headers(buyer),
            json={
                "event_id": event_id,
                "items": [{"ticket_type_id": tier_id, "quantity": 1}],
            },
        )
    ).json()
    order_obj = await get_order(db_session, uuid.UUID(order["id"]))
    order_obj.status = OrderStatus.CONFIRMED.value
    buyer_obj = await get_user_with_profile(db_session, buyer.id)
    await att_services.generate_attendees_for_order(db_session, order_obj, buyer_obj)
    await db_session.commit()
    attendees = await list_for_event(db_session, uuid.UUID(event_id))
    await client.post(
        "/api/v1/attendees/check-in",
        headers=auth_headers(organizer),
        json={"ticket_code": attendees[0].ticket_code},
    )

    # Submit a review (invalidates the summary), then read it (populates cache).
    await client.post(
        f"{EVENTS_URL}/{event_id}/reviews",
        headers=auth_headers(buyer),
        json={"rating": 5},
    )
    first = await client.get(f"{EVENTS_URL}/{event_id}/reviews/summary")
    assert first.status_code == 200
    body = first.json()
    assert body["total_reviews"] == 1
    assert body["average_rating"] == 5.0
    assert body["distribution"]["5"] == 1

    # A cache hit must reconstruct the int-keyed distribution intact.
    second = await client.get(f"{EVENTS_URL}/{event_id}/reviews/summary")
    assert second.json() == body
