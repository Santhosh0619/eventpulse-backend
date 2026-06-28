"""Tests for the tickets feature: tier CRUD, availability, and reservation."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

ORGS_URL = "/api/v1/organizations"
EVENTS_URL = "/api/v1/events"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


async def _setup_event(client: AsyncClient, headers: dict) -> tuple[str, str]:
    """Create an org and event; return (org_id, event_id)."""
    org = await client.post(
        ORGS_URL,
        headers=headers,
        json={"name": "Ticket Org", "contact_email": "o@example.com"},
    )
    org_id = org.json()["id"]
    event = await client.post(
        EVENTS_URL,
        headers=headers,
        json={
            "organization_id": org_id,
            "title": "Ticketed Event",
            "description": "d",
            "venue_name": "v",
            "start_datetime": START,
            "end_datetime": END,
        },
    )
    return org_id, event.json()["id"]


def _tiers_url(event_id: str) -> str:
    return f"{EVENTS_URL}/{event_id}/ticket-types"


async def _create_tier(client, headers, event_id, **over):
    payload = {"name": "General", "price": "20.00", "quantity_total": 50}
    payload.update(over)
    return await client.post(_tiers_url(event_id), headers=headers, json=payload)


async def _add_member(client, owner_headers, org_id, member, member_headers, role):
    inv = await client.post(
        f"{ORGS_URL}/{org_id}/members/invite",
        headers=owner_headers,
        json={"email": member.email, "role": role},
    )
    token = inv.json()["invitation_token"]
    await client.post(f"{ORGS_URL}/invitations/{token}/accept", headers=member_headers)


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #


async def test_create_tier_success(client, verified_user, auth_headers) -> None:
    """An org owner can create a ticket tier."""
    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    resp = await _create_tier(client, headers, event_id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "General"
    assert body["quantity_sold"] == 0


async def test_create_tier_requires_admin(client, make_user, auth_headers) -> None:
    """A plain member cannot create ticket tiers (requires admin or owner)."""
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    org_id, event_id = await _setup_event(client, auth_headers(owner))
    await _add_member(
        client, auth_headers(owner), org_id, member, auth_headers(member), "member"
    )
    resp = await _create_tier(client, auth_headers(member), event_id)
    assert resp.status_code == 403


async def test_create_tier_requires_auth(client, verified_user, auth_headers) -> None:
    """Creating a tier without auth returns 401."""
    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    resp = await client.post(
        _tiers_url(event_id),
        json={"name": "G", "price": "1.00", "quantity_total": 1},
    )
    assert resp.status_code == 401


async def test_create_tier_negative_price_returns_422(
    client, verified_user, auth_headers
) -> None:
    """A negative price is rejected with 422."""
    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    resp = await _create_tier(client, headers, event_id, price="-5.00")
    assert resp.status_code == 422


async def test_create_tier_zero_quantity_returns_422(
    client, verified_user, auth_headers
) -> None:
    """A non-positive quantity_total is rejected with 422."""
    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    resp = await _create_tier(client, headers, event_id, quantity_total=0)
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# list / update / delete / availability
# --------------------------------------------------------------------------- #


async def test_list_tiers_public(client, verified_user, auth_headers) -> None:
    """Ticket tiers are publicly listable."""
    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    await _create_tier(client, headers, event_id, name="VIP")
    resp = await client.get(_tiers_url(event_id))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_update_tier_success(client, verified_user, auth_headers) -> None:
    """An owner can update a tier's price and quantity."""
    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    tier = (await _create_tier(client, headers, event_id)).json()
    resp = await client.put(
        f"{_tiers_url(event_id)}/{tier['id']}",
        headers=headers,
        json={"price": "35.00", "quantity_total": 75},
    )
    assert resp.status_code == 200
    assert resp.json()["quantity_total"] == 75


async def test_update_tier_not_found_returns_404(
    client, verified_user, auth_headers
) -> None:
    """Updating a tier that doesn't belong to the event returns 404."""
    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    resp = await client.put(
        f"{_tiers_url(event_id)}/{uuid.uuid4()}",
        headers=headers,
        json={"price": "5.00"},
    )
    assert resp.status_code == 404


async def test_delete_tier_success(client, verified_user, auth_headers) -> None:
    """An owner can delete a tier with no sales."""
    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    tier = (await _create_tier(client, headers, event_id)).json()
    resp = await client.delete(f"{_tiers_url(event_id)}/{tier['id']}", headers=headers)
    assert resp.status_code == 204


async def test_availability_endpoint(client, verified_user, auth_headers) -> None:
    """Availability reports per-tier and total available counts."""
    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    await _create_tier(client, headers, event_id, quantity_total=10)
    resp = await client.get(f"{EVENTS_URL}/{event_id}/availability")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_available"] == 10
    assert body["tiers"][0]["quantity_available"] == 10
    assert body["tiers"][0]["is_on_sale"] is True


# --------------------------------------------------------------------------- #
# reservation / oversell protection
# --------------------------------------------------------------------------- #


async def test_atomic_reserve_prevents_oversell(
    client, verified_user, auth_headers, db_session: AsyncSession
) -> None:
    """Reserving beyond quantity_total raises and never oversells."""
    from app.core.exceptions import BadRequestError
    from app.features.tickets import services as ticket_services

    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    tier = (await _create_tier(client, headers, event_id, quantity_total=2)).json()
    tier_id = uuid.UUID(tier["id"])

    await ticket_services.atomic_reserve(db_session, tier_id, 2)
    with pytest.raises(BadRequestError):
        await ticket_services.atomic_reserve(db_session, tier_id, 1)


async def test_delete_tier_with_sales_returns_409(
    client, verified_user, auth_headers, db_session: AsyncSession
) -> None:
    """A tier with existing sales cannot be deleted."""
    from app.features.tickets import services as ticket_services

    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    tier = (await _create_tier(client, headers, event_id, quantity_total=5)).json()
    await ticket_services.atomic_reserve(db_session, uuid.UUID(tier["id"]), 1)

    resp = await client.delete(f"{_tiers_url(event_id)}/{tier['id']}", headers=headers)
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# publish integration (Phase 5 rule)
# --------------------------------------------------------------------------- #


async def test_publish_requires_active_ticket_type(
    client, verified_user, auth_headers
) -> None:
    """Publishing is blocked until the event has an active ticket type."""
    headers = auth_headers(verified_user)
    _, event_id = await _setup_event(client, headers)
    blocked = await client.post(f"{EVENTS_URL}/{event_id}/publish", headers=headers)
    assert blocked.status_code == 400

    await _create_tier(client, headers, event_id)
    ok = await client.post(f"{EVENTS_URL}/{event_id}/publish", headers=headers)
    assert ok.status_code == 200
    assert ok.json()["status"] == "published"
