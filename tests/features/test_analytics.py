"""Tests for analytics: event sales, attendance, org overview, platform dashboard."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

ANALYTICS_URL = "/api/v1/analytics"
ORGS_URL = "/api/v1/organizations"
EVENTS_URL = "/api/v1/events"
ORDERS_URL = "/api/v1/orders"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


async def _setup_confirmed_order(
    client: AsyncClient,
    db_session: AsyncSession,
    organizer,
    buyer,
    auth_headers,
    *,
    quantity: int = 2,
    check_in: bool = False,
):
    """Create org+event+tier, place an order, confirm it, and issue attendees.

    Returns ``(org_id, event_id, tier_id)``. Mirrors the real confirmation path
    (order -> CONFIRMED + attendees) without going through Stripe.
    """
    from app.features.attendees import services as att_services
    from app.features.attendees.crud import list_for_event
    from app.features.orders.crud import get_order
    from app.features.users.crud import get_user_with_profile
    from app.shared.enums import OrderStatus

    org = (
        await client.post(
            ORGS_URL,
            headers=auth_headers(organizer),
            json={"name": "An Org", "contact_email": "o@example.com"},
        )
    ).json()
    event = (
        await client.post(
            EVENTS_URL,
            headers=auth_headers(organizer),
            json={
                "organization_id": org["id"],
                "title": "An Event",
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
                "items": [{"ticket_type_id": tier["id"], "quantity": quantity}],
            },
        )
    ).json()

    from datetime import UTC, datetime

    order_obj = await get_order(db_session, uuid.UUID(order["id"]))
    order_obj.status = OrderStatus.CONFIRMED.value
    order_obj.confirmed_at = datetime.now(UTC)
    buyer_obj = await get_user_with_profile(db_session, buyer.id)
    await att_services.generate_attendees_for_order(db_session, order_obj, buyer_obj)
    await db_session.commit()

    if check_in:
        attendees = await list_for_event(db_session, uuid.UUID(event["id"]))
        await client.post(
            "/api/v1/attendees/check-in",
            headers=auth_headers(organizer),
            json={"ticket_code": attendees[0].ticket_code},
        )

    return org["id"], event["id"], tier["id"]


# --------------------------------------------------------------------------- #
# event sales
# --------------------------------------------------------------------------- #


async def test_event_sales(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Sales analytics reflects the confirmed order's revenue and tickets."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    _, event_id, tier_id = await _setup_confirmed_order(
        client, db_session, organizer, buyer, auth_headers, quantity=2
    )

    resp = await client.get(
        f"{ANALYTICS_URL}/events/{event_id}/sales", headers=auth_headers(organizer)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_orders"] == 1
    assert body["total_tickets_sold"] == 2
    assert float(body["total_revenue"]) == 20.0
    assert len(body["tiers"]) == 1
    assert body["tiers"][0]["ticket_type_id"] == tier_id
    assert body["tiers"][0]["tickets_sold"] == 2
    assert len(body["daily"]) == 1


async def test_event_sales_forbidden_for_non_member(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A non-member cannot read an event's sales analytics."""
    organizer = await make_user(email="org2@example.com")
    buyer = await make_user(email="buyer2@example.com")
    outsider = await make_user(email="outsider@example.com")
    _, event_id, _ = await _setup_confirmed_order(
        client, db_session, organizer, buyer, auth_headers
    )
    resp = await client.get(
        f"{ANALYTICS_URL}/events/{event_id}/sales", headers=auth_headers(outsider)
    )
    assert resp.status_code == 403


async def test_event_sales_requires_auth(client: AsyncClient) -> None:
    """Sales analytics requires authentication."""
    resp = await client.get(f"{ANALYTICS_URL}/events/{uuid.uuid4()}/sales")
    assert resp.status_code == 401


async def test_event_sales_unknown_event_404(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Sales analytics for an unknown event returns 404."""
    resp = await client.get(
        f"{ANALYTICS_URL}/events/{uuid.uuid4()}/sales",
        headers=auth_headers(verified_user),
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# attendance
# --------------------------------------------------------------------------- #


async def test_event_attendance(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Attendance analytics reflects generated attendees and one check-in."""
    organizer = await make_user(email="org3@example.com")
    buyer = await make_user(email="buyer3@example.com")
    _, event_id, _ = await _setup_confirmed_order(
        client, db_session, organizer, buyer, auth_headers, quantity=2, check_in=True
    )

    resp = await client.get(
        f"{ANALYTICS_URL}/events/{event_id}/attendance",
        headers=auth_headers(organizer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["checked_in"] == 1
    assert body["not_checked_in"] == 1
    assert body["check_in_rate"] == 0.5
    assert sum(h["count"] for h in body["hourly"]) == 1


# --------------------------------------------------------------------------- #
# org overview
# --------------------------------------------------------------------------- #


async def test_org_overview(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Org overview aggregates events, revenue, tickets, and attendees."""
    organizer = await make_user(email="org4@example.com")
    buyer = await make_user(email="buyer4@example.com")
    org_id, _, _ = await _setup_confirmed_order(
        client, db_session, organizer, buyer, auth_headers, quantity=3
    )

    resp = await client.get(
        f"{ANALYTICS_URL}/organizations/{org_id}/overview",
        headers=auth_headers(organizer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_events"] == 1
    assert body["published_events"] == 1
    assert body["total_orders"] == 1
    assert body["total_tickets_sold"] == 3
    assert body["total_attendees"] == 3
    assert float(body["total_revenue"]) == 30.0


async def test_org_overview_forbidden_non_member(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A non-member cannot read an org's overview."""
    organizer = await make_user(email="org5@example.com")
    buyer = await make_user(email="buyer5@example.com")
    outsider = await make_user(email="outsider5@example.com")
    org_id, _, _ = await _setup_confirmed_order(
        client, db_session, organizer, buyer, auth_headers
    )
    resp = await client.get(
        f"{ANALYTICS_URL}/organizations/{org_id}/overview",
        headers=auth_headers(outsider),
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# platform dashboard
# --------------------------------------------------------------------------- #


async def test_platform_dashboard_admin(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """An admin can read the platform dashboard with aggregate totals."""
    admin = await make_user(email="admin@example.com", role="admin")
    organizer = await make_user(email="org6@example.com")
    buyer = await make_user(email="buyer6@example.com")
    await _setup_confirmed_order(
        client, db_session, organizer, buyer, auth_headers, quantity=2
    )

    resp = await client.get(f"{ANALYTICS_URL}/platform", headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_users"] >= 3
    assert body["total_organizations"] >= 1
    assert body["total_events"] >= 1
    assert body["total_orders"] >= 1
    assert body["total_tickets_sold"] >= 2
    assert float(body["total_revenue"]) >= 20.0


async def test_platform_dashboard_forbidden_non_admin(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """A non-admin cannot read the platform dashboard."""
    resp = await client.get(
        f"{ANALYTICS_URL}/platform", headers=auth_headers(verified_user)
    )
    assert resp.status_code == 403
