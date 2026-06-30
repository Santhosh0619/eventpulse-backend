"""Tests for the attendees feature: check-in, listing, stats, export, QR."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

ORGS_URL = "/api/v1/organizations"
EVENTS_URL = "/api/v1/events"
ORDERS_URL = "/api/v1/orders"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


async def _setup_published_event(client: AsyncClient, headers: dict) -> tuple[str, str]:
    """Create an org + event + active tier and publish; return (event_id, tier_id)."""
    org = (
        await client.post(
            ORGS_URL,
            headers=headers,
            json={"name": "Att Org", "contact_email": "o@example.com"},
        )
    ).json()
    event = (
        await client.post(
            EVENTS_URL,
            headers=headers,
            json={
                "organization_id": org["id"],
                "title": "Att Event",
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
            json={"name": "GA", "price": "10.00", "quantity_total": 50},
        )
    ).json()
    await client.post(f"{EVENTS_URL}/{event['id']}/publish", headers=headers)
    return event["id"], tier["id"]


async def _place_order_with_attendees(
    client: AsyncClient,
    organizer,
    buyer,
    auth_headers,
    db_session: AsyncSession,
    quantity: int = 2,
) -> tuple[str, list]:
    """Set up a published event, place an order, and generate attendee rows.

    Returns (event_id, attendees) where attendees are the generated ORM rows.
    """
    from app.features.attendees import services as att_services
    from app.features.attendees.crud import list_for_event
    from app.features.orders.crud import get_order
    from app.features.users.crud import get_user_with_profile

    event_id, tier_id = await _setup_published_event(client, auth_headers(organizer))
    order = (
        await client.post(
            ORDERS_URL,
            headers=auth_headers(buyer),
            json={
                "event_id": event_id,
                "items": [{"ticket_type_id": tier_id, "quantity": quantity}],
            },
        )
    ).json()

    order_obj = await get_order(db_session, uuid.UUID(order["id"]))
    buyer_obj = await get_user_with_profile(db_session, buyer.id)
    await att_services.generate_attendees_for_order(db_session, order_obj, buyer_obj)
    await db_session.commit()

    attendees = await list_for_event(db_session, uuid.UUID(event_id))
    return event_id, attendees


# --------------------------------------------------------------------------- #
# generation
# --------------------------------------------------------------------------- #


async def test_generate_attendees_creates_one_per_ticket(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Generating attendees produces one row per ticket with unique codes."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    _, attendees = await _place_order_with_attendees(
        client, organizer, buyer, auth_headers, db_session, quantity=3
    )
    assert len(attendees) == 3
    codes = {a.ticket_code for a in attendees}
    assert len(codes) == 3
    assert all(c.startswith("EP-ATT-") for c in codes)


# --------------------------------------------------------------------------- #
# check-in
# --------------------------------------------------------------------------- #


async def test_check_in_success_then_idempotent(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Checking in succeeds once, then reports already-checked-in on repeat."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    _, attendees = await _place_order_with_attendees(
        client, organizer, buyer, auth_headers, db_session
    )
    code = attendees[0].ticket_code

    first = await client.post(
        "/api/v1/attendees/check-in",
        headers=auth_headers(organizer),
        json={"ticket_code": code},
    )
    assert first.status_code == 200
    assert first.json()["already_checked_in"] is False

    second = await client.post(
        "/api/v1/attendees/check-in",
        headers=auth_headers(organizer),
        json={"ticket_code": code},
    )
    assert second.status_code == 200
    assert second.json()["already_checked_in"] is True


async def test_check_in_unknown_code_returns_404(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Checking in an unknown ticket code returns 404."""
    staff = await make_user(email="staff@example.com")
    resp = await client.post(
        "/api/v1/attendees/check-in",
        headers=auth_headers(staff),
        json={"ticket_code": "EP-ATT-deadbeef"},
    )
    assert resp.status_code == 404


async def test_check_in_non_member_returns_403(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A non-member of the event's org cannot check attendees in."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    outsider = await make_user(email="outsider@example.com")
    _, attendees = await _place_order_with_attendees(
        client, organizer, buyer, auth_headers, db_session
    )
    resp = await client.post(
        "/api/v1/attendees/check-in",
        headers=auth_headers(outsider),
        json={"ticket_code": attendees[0].ticket_code},
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# list / stats / export
# --------------------------------------------------------------------------- #


async def test_list_attendees_member_only(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Org members can list attendees; outsiders get 403."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    outsider = await make_user(email="outsider@example.com")
    event_id, _ = await _place_order_with_attendees(
        client, organizer, buyer, auth_headers, db_session
    )
    ok = await client.get(
        f"{EVENTS_URL}/{event_id}/attendees", headers=auth_headers(organizer)
    )
    assert ok.status_code == 200
    assert len(ok.json()) == 2
    forbidden = await client.get(
        f"{EVENTS_URL}/{event_id}/attendees", headers=auth_headers(outsider)
    )
    assert forbidden.status_code == 403


async def test_list_my_attendees_returns_own_tickets(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A buyer sees only their own attendee records via /users/me/attendees."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, _ = await _place_order_with_attendees(
        client, organizer, buyer, auth_headers, db_session
    )

    mine = await client.get(
        "/api/v1/users/me/attendees", headers=auth_headers(buyer)
    )
    assert mine.status_code == 200
    body = mine.json()
    assert len(body) == 2
    assert all(a["ticket_code"].startswith("EP-ATT-") for a in body)

    # The organizer (a different user) has no tickets of their own.
    organizer_tickets = await client.get(
        "/api/v1/users/me/attendees", headers=auth_headers(organizer)
    )
    assert organizer_tickets.status_code == 200
    assert organizer_tickets.json() == []


async def test_list_my_attendees_filters_by_event(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """The event_id query param narrows my tickets to one event."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, _ = await _place_order_with_attendees(
        client, organizer, buyer, auth_headers, db_session
    )

    match = await client.get(
        "/api/v1/users/me/attendees",
        headers=auth_headers(buyer),
        params={"event_id": event_id},
    )
    assert match.status_code == 200
    assert len(match.json()) == 2

    other = await client.get(
        "/api/v1/users/me/attendees",
        headers=auth_headers(buyer),
        params={"event_id": str(uuid.uuid4())},
    )
    assert other.status_code == 200
    assert other.json() == []


async def test_list_my_attendees_requires_auth(client: AsyncClient) -> None:
    """The my-tickets endpoint requires authentication."""
    resp = await client.get("/api/v1/users/me/attendees")
    assert resp.status_code == 401


async def test_attendee_stats(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Stats reflect total and checked-in counts."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, attendees = await _place_order_with_attendees(
        client, organizer, buyer, auth_headers, db_session
    )
    await client.post(
        "/api/v1/attendees/check-in",
        headers=auth_headers(organizer),
        json={"ticket_code": attendees[0].ticket_code},
    )
    resp = await client.get(
        f"{EVENTS_URL}/{event_id}/attendees/stats", headers=auth_headers(organizer)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["checked_in"] == 1
    assert body["check_in_rate"] == 0.5


async def _add_member(client, owner_headers, org_id, member, member_headers, role):
    """Invite + accept a member into the org."""
    inv = await client.post(
        f"{ORGS_URL}/{org_id}/members/invite",
        headers=owner_headers,
        json={"email": member.email, "role": role},
    )
    token = inv.json()["invitation_token"]
    await client.post(f"{ORGS_URL}/invitations/{token}/accept", headers=member_headers)


async def test_export_denied_for_plain_member(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A plain member (non-admin) cannot export the attendee CSV."""
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    org = (
        await client.post(
            ORGS_URL,
            headers=auth_headers(owner),
            json={"name": "Exp Org", "contact_email": "o@example.com"},
        )
    ).json()
    await _add_member(
        client, auth_headers(owner), org["id"], member, auth_headers(member), "member"
    )
    event = (
        await client.post(
            EVENTS_URL,
            headers=auth_headers(owner),
            json={
                "organization_id": org["id"],
                "title": "Exp Event",
                "description": "d",
                "venue_name": "v",
                "start_datetime": START,
                "end_datetime": END,
            },
        )
    ).json()
    resp = await client.get(
        f"{EVENTS_URL}/{event['id']}/attendees/export", headers=auth_headers(member)
    )
    assert resp.status_code == 403


async def test_stats_zero_attendees(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Stats for an event with no attendees report zero and rate 0.0."""
    organizer = await make_user(email="org@example.com")
    event_id, _ = await _setup_published_event(client, auth_headers(organizer))
    resp = await client.get(
        f"{EVENTS_URL}/{event_id}/attendees/stats", headers=auth_headers(organizer)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["check_in_rate"] == 0.0


async def test_attendee_qr_admin_override(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A platform admin can fetch any attendee's QR code."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    admin = await make_user(email="admin@example.com", role="admin")
    _, attendees = await _place_order_with_attendees(
        client, organizer, buyer, auth_headers, db_session
    )
    resp = await client.get(
        f"/api/v1/attendees/{attendees[0].id}/qr", headers=auth_headers(admin)
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


async def test_export_csv_admin_only(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """CSV export is available to org admins/owners and returns CSV content."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, _ = await _place_order_with_attendees(
        client, organizer, buyer, auth_headers, db_session
    )
    resp = await client.get(
        f"{EVENTS_URL}/{event_id}/attendees/export", headers=auth_headers(organizer)
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "ticket_code" in resp.text


# --------------------------------------------------------------------------- #
# QR
# --------------------------------------------------------------------------- #


async def test_attendee_qr_owner(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """The ticket holder can fetch their QR code as a PNG."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    _, attendees = await _place_order_with_attendees(
        client, organizer, buyer, auth_headers, db_session
    )
    resp = await client.get(
        f"/api/v1/attendees/{attendees[0].id}/qr", headers=auth_headers(buyer)
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_attendee_qr_non_owner_returns_403(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """A non-owner cannot fetch someone else's ticket QR."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    other = await make_user(email="other@example.com")
    _, attendees = await _place_order_with_attendees(
        client, organizer, buyer, auth_headers, db_session
    )
    resp = await client.get(
        f"/api/v1/attendees/{attendees[0].id}/qr", headers=auth_headers(other)
    )
    assert resp.status_code == 403
