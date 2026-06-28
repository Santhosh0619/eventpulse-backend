"""Tests for the orders feature: placement, listing, retrieval, cancellation."""

import uuid

from httpx import AsyncClient

ORGS_URL = "/api/v1/organizations"
EVENTS_URL = "/api/v1/events"
ORDERS_URL = "/api/v1/orders"
MY_ORDERS_URL = "/api/v1/users/me/orders"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


async def _setup_published_event(
    client: AsyncClient, headers: dict, quantity_total: int = 100
) -> tuple[str, str]:
    """Create an org + event + active tier and publish; return (event_id, tier_id)."""
    org = (
        await client.post(
            ORGS_URL,
            headers=headers,
            json={"name": "Order Org", "contact_email": "o@example.com"},
        )
    ).json()
    event = (
        await client.post(
            EVENTS_URL,
            headers=headers,
            json={
                "organization_id": org["id"],
                "title": "Order Event",
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
            headers=headers,
            json={
                "name": "GA",
                "price": "25.00",
                "quantity_total": quantity_total,
                "max_per_order": 5,
            },
        )
    ).json()
    await client.post(f"{EVENTS_URL}/{event['id']}/publish", headers=headers)
    return event["id"], tier["id"]


def _order_payload(event_id: str, tier_id: str, quantity: int = 2) -> dict:
    """Build an order payload for one tier."""
    return {
        "event_id": event_id,
        "items": [{"ticket_type_id": tier_id, "quantity": quantity}],
    }


# --------------------------------------------------------------------------- #
# place order
# --------------------------------------------------------------------------- #


async def test_place_order_success(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Placing an order confirms it, computes totals, and reserves inventory."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, tier_id = await _setup_published_event(client, auth_headers(organizer))

    resp = await client.post(
        ORDERS_URL,
        headers=auth_headers(buyer),
        json=_order_payload(event_id, tier_id, 2),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "confirmed"
    assert body["order_number"].startswith("EP-")
    assert body["total_amount"] == "50.00"
    assert body["items"][0]["quantity"] == 2

    # Inventory decremented.
    avail = await client.get(f"{EVENTS_URL}/{event_id}/availability")
    assert avail.json()["tiers"][0]["quantity_sold"] == 2


async def test_place_order_requires_auth(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Placing an order without auth returns 401."""
    organizer = await make_user(email="org@example.com")
    event_id, tier_id = await _setup_published_event(client, auth_headers(organizer))
    resp = await client.post(ORDERS_URL, json=_order_payload(event_id, tier_id))
    assert resp.status_code == 401


async def test_place_order_unpublished_event_returns_400(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Ordering for a draft event is rejected with 400."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    headers = auth_headers(organizer)
    org = (
        await client.post(
            ORGS_URL,
            headers=headers,
            json={"name": "Draft Org", "contact_email": "o@example.com"},
        )
    ).json()
    event = (
        await client.post(
            EVENTS_URL,
            headers=headers,
            json={
                "organization_id": org["id"],
                "title": "Draft Event",
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
            headers=headers,
            json={"name": "GA", "price": "10.00", "quantity_total": 10},
        )
    ).json()
    # Event left as draft (not published).
    resp = await client.post(
        ORDERS_URL,
        headers=auth_headers(buyer),
        json=_order_payload(event["id"], tier["id"]),
    )
    assert resp.status_code == 400


async def test_place_order_insufficient_inventory_returns_400(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Ordering more than available inventory returns 400."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, tier_id = await _setup_published_event(
        client, auth_headers(organizer), quantity_total=3
    )
    resp = await client.post(
        ORDERS_URL,
        headers=auth_headers(buyer),
        json={
            "event_id": event_id,
            "items": [{"ticket_type_id": tier_id, "quantity": 5}],
        },
    )
    # quantity 5 exceeds available 3 -> reserve fails (also exceeds max_per_order)
    assert resp.status_code == 400


async def test_place_order_exceeds_max_per_order_returns_400(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Ordering more than max_per_order returns 400."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, tier_id = await _setup_published_event(
        client, auth_headers(organizer), quantity_total=100
    )
    # max_per_order is 5 in the helper.
    resp = await client.post(
        ORDERS_URL,
        headers=auth_headers(buyer),
        json={
            "event_id": event_id,
            "items": [{"ticket_type_id": tier_id, "quantity": 6}],
        },
    )
    assert resp.status_code == 400


async def test_place_order_no_items_returns_422(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """An order with no items is rejected with 422."""
    buyer = await make_user(email="buyer@example.com")
    resp = await client.post(
        ORDERS_URL,
        headers=auth_headers(buyer),
        json={"event_id": str(uuid.uuid4()), "items": []},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# list / get / cancel
# --------------------------------------------------------------------------- #


async def test_list_my_orders(client: AsyncClient, make_user, auth_headers) -> None:
    """A user can list their own orders."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, tier_id = await _setup_published_event(client, auth_headers(organizer))
    await client.post(
        ORDERS_URL, headers=auth_headers(buyer), json=_order_payload(event_id, tier_id)
    )
    resp = await client.get(MY_ORDERS_URL, headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_get_order_owner_and_non_owner(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """The owner can read an order; another user gets 403."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    other = await make_user(email="other@example.com")
    event_id, tier_id = await _setup_published_event(client, auth_headers(organizer))
    order = (
        await client.post(
            ORDERS_URL,
            headers=auth_headers(buyer),
            json=_order_payload(event_id, tier_id),
        )
    ).json()

    ok = await client.get(f"{ORDERS_URL}/{order['id']}", headers=auth_headers(buyer))
    assert ok.status_code == 200
    forbidden = await client.get(
        f"{ORDERS_URL}/{order['id']}", headers=auth_headers(other)
    )
    assert forbidden.status_code == 403


async def test_get_order_not_found_returns_404(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Fetching an unknown order returns 404."""
    buyer = await make_user(email="buyer@example.com")
    resp = await client.get(f"{ORDERS_URL}/{uuid.uuid4()}", headers=auth_headers(buyer))
    assert resp.status_code == 404


async def test_cancel_order_releases_inventory(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Cancelling an order releases its reserved tickets."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, tier_id = await _setup_published_event(client, auth_headers(organizer))
    order = (
        await client.post(
            ORDERS_URL,
            headers=auth_headers(buyer),
            json=_order_payload(event_id, tier_id, 3),
        )
    ).json()

    resp = await client.post(
        f"{ORDERS_URL}/{order['id']}/cancel", headers=auth_headers(buyer)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    avail = await client.get(f"{EVENTS_URL}/{event_id}/availability")
    assert avail.json()["tiers"][0]["quantity_sold"] == 0


async def test_cancel_order_non_owner_returns_403(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A non-owner cannot cancel someone else's order."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    other = await make_user(email="other@example.com")
    event_id, tier_id = await _setup_published_event(client, auth_headers(organizer))
    order = (
        await client.post(
            ORDERS_URL,
            headers=auth_headers(buyer),
            json=_order_payload(event_id, tier_id),
        )
    ).json()
    resp = await client.post(
        f"{ORDERS_URL}/{order['id']}/cancel", headers=auth_headers(other)
    )
    assert resp.status_code == 403


async def test_cancel_already_cancelled_returns_400(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Cancelling an already-cancelled order returns 400."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, tier_id = await _setup_published_event(client, auth_headers(organizer))
    order = (
        await client.post(
            ORDERS_URL,
            headers=auth_headers(buyer),
            json=_order_payload(event_id, tier_id),
        )
    ).json()
    await client.post(f"{ORDERS_URL}/{order['id']}/cancel", headers=auth_headers(buyer))
    again = await client.post(
        f"{ORDERS_URL}/{order['id']}/cancel", headers=auth_headers(buyer)
    )
    assert again.status_code == 400
