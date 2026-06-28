"""Tests for the payments feature: intents, webhooks, and refunds (Stripe mocked)."""

import uuid

import pytest
from httpx import AsyncClient

import app.features.payments.gateway as gateway_mod

ORGS_URL = "/api/v1/organizations"
EVENTS_URL = "/api/v1/events"
ORDERS_URL = "/api/v1/orders"
INTENT_URL = "/api/v1/payments/create-intent"
WEBHOOK_URL = "/api/v1/webhooks/stripe"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"
INTENT_ID = "pi_test_123"


@pytest.fixture(autouse=True)
def mock_stripe(monkeypatch):
    """Patch the Stripe gateway so no network calls happen during tests."""

    async def fake_create_intent(amount_minor, currency, metadata):
        return {"id": INTENT_ID, "client_secret": f"{INTENT_ID}_secret"}

    async def fake_create_refund(payment_intent_id, amount_minor):
        return {"id": "re_test_123", "amount": amount_minor}

    monkeypatch.setattr(gateway_mod, "create_payment_intent", fake_create_intent)
    monkeypatch.setattr(gateway_mod, "create_refund", fake_create_refund)


def _succeeded_event() -> dict:
    """Build a Stripe payment_intent.succeeded event for the test intent."""
    return {
        "id": "evt_succeeded_1",
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": INTENT_ID, "payment_method_types": ["card"]}},
    }


async def _setup_pending_order(client, organizer, buyer, auth_headers, qty=2):
    """Create a published event + tier and place a pending order; return ids."""
    org = (
        await client.post(
            ORGS_URL,
            headers=auth_headers(organizer),
            json={"name": "Pay Org", "contact_email": "o@example.com"},
        )
    ).json()
    event = (
        await client.post(
            EVENTS_URL,
            headers=auth_headers(organizer),
            json={
                "organization_id": org["id"],
                "title": "Pay Event",
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
            json={"name": "GA", "price": "25.00", "quantity_total": 50},
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
                "items": [{"ticket_type_id": tier["id"], "quantity": qty}],
            },
        )
    ).json()
    return event["id"], order["id"]


# --------------------------------------------------------------------------- #
# create-intent
# --------------------------------------------------------------------------- #


async def test_create_intent_success(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Creating an intent for a pending order returns a client secret."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    _, order_id = await _setup_pending_order(client, organizer, buyer, auth_headers)
    resp = await client.post(
        INTENT_URL, headers=auth_headers(buyer), json={"order_id": order_id}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_secret"] == f"{INTENT_ID}_secret"
    assert body["amount"] == "50.00"


async def test_create_intent_non_owner_returns_403(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A non-owner cannot create a payment intent for someone else's order."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    other = await make_user(email="other@example.com")
    _, order_id = await _setup_pending_order(client, organizer, buyer, auth_headers)
    resp = await client.post(
        INTENT_URL, headers=auth_headers(other), json={"order_id": order_id}
    )
    assert resp.status_code == 403


async def test_create_intent_order_not_found_returns_404(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Creating an intent for an unknown order returns 404."""
    buyer = await make_user(email="buyer@example.com")
    resp = await client.post(
        INTENT_URL, headers=auth_headers(buyer), json={"order_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404


async def test_create_intent_cancelled_order_returns_400(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Creating an intent for a non-pending order returns 400."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    _, order_id = await _setup_pending_order(client, organizer, buyer, auth_headers)
    await client.post(f"{ORDERS_URL}/{order_id}/cancel", headers=auth_headers(buyer))
    resp = await client.post(
        INTENT_URL, headers=auth_headers(buyer), json={"order_id": order_id}
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# webhook
# --------------------------------------------------------------------------- #


async def test_webhook_succeeded_confirms_order_and_issues_tickets(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """A succeeded webhook confirms the order and generates attendees."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, order_id = await _setup_pending_order(
        client, organizer, buyer, auth_headers
    )
    await client.post(
        INTENT_URL, headers=auth_headers(buyer), json={"order_id": order_id}
    )

    monkeypatch.setattr(
        gateway_mod, "construct_event", lambda payload, sig: _succeeded_event()
    )
    resp = await client.post(
        WEBHOOK_URL, content=b"{}", headers={"stripe-signature": "test"}
    )
    assert resp.status_code == 200

    order = await client.get(f"{ORDERS_URL}/{order_id}", headers=auth_headers(buyer))
    assert order.json()["status"] == "confirmed"
    attendees = await client.get(
        f"{EVENTS_URL}/{event_id}/attendees", headers=auth_headers(organizer)
    )
    assert len(attendees.json()) == 2


async def test_webhook_succeeded_is_idempotent(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """Replaying a succeeded webhook does not duplicate attendees."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, order_id = await _setup_pending_order(
        client, organizer, buyer, auth_headers
    )
    await client.post(
        INTENT_URL, headers=auth_headers(buyer), json={"order_id": order_id}
    )
    monkeypatch.setattr(
        gateway_mod, "construct_event", lambda payload, sig: _succeeded_event()
    )
    await client.post(WEBHOOK_URL, content=b"{}", headers={"stripe-signature": "t"})
    await client.post(WEBHOOK_URL, content=b"{}", headers={"stripe-signature": "t"})

    attendees = await client.get(
        f"{EVENTS_URL}/{event_id}/attendees", headers=auth_headers(organizer)
    )
    assert len(attendees.json()) == 2


async def test_webhook_invalid_signature_returns_400(
    client: AsyncClient, monkeypatch
) -> None:
    """An invalid webhook signature is rejected with 400."""

    def _raise(payload, sig):
        raise ValueError("bad signature")

    monkeypatch.setattr(gateway_mod, "construct_event", _raise)
    resp = await client.post(
        WEBHOOK_URL, content=b"{}", headers={"stripe-signature": "bad"}
    )
    assert resp.status_code == 400


async def test_webhook_payment_failed_marks_failed(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """A failed webhook leaves the order pending (not confirmed)."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    _, order_id = await _setup_pending_order(client, organizer, buyer, auth_headers)
    await client.post(
        INTENT_URL, headers=auth_headers(buyer), json={"order_id": order_id}
    )

    failed_event = {
        "id": "evt_failed_1",
        "type": "payment_intent.payment_failed",
        "data": {"object": {"id": INTENT_ID}},
    }
    monkeypatch.setattr(
        gateway_mod, "construct_event", lambda payload, sig: failed_event
    )
    resp = await client.post(
        WEBHOOK_URL, content=b"{}", headers={"stripe-signature": "t"}
    )
    assert resp.status_code == 200
    order = await client.get(f"{ORDERS_URL}/{order_id}", headers=auth_headers(buyer))
    assert order.json()["status"] == "pending"


# --------------------------------------------------------------------------- #
# refund
# --------------------------------------------------------------------------- #


async def _confirm_via_webhook(client, buyer, order_id, auth_headers, monkeypatch):
    """Helper: create intent and fire a succeeded webhook to confirm the order."""
    await client.post(
        INTENT_URL, headers=auth_headers(buyer), json={"order_id": order_id}
    )
    monkeypatch.setattr(
        gateway_mod, "construct_event", lambda payload, sig: _succeeded_event()
    )
    await client.post(WEBHOOK_URL, content=b"{}", headers={"stripe-signature": "t"})


async def test_refund_success_releases_inventory(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """An org admin can refund a paid order, releasing inventory."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, order_id = await _setup_pending_order(
        client, organizer, buyer, auth_headers
    )
    await _confirm_via_webhook(client, buyer, order_id, auth_headers, monkeypatch)

    resp = await client.post(
        f"{ORDERS_URL}/{order_id}/refund",
        headers=auth_headers(organizer),
        json={"reason": "customer request"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["order_status"] == "refunded"
    assert body["payment_status"] == "refunded"

    avail = await client.get(f"{EVENTS_URL}/{event_id}/availability")
    assert avail.json()["tiers"][0]["quantity_sold"] == 0


async def test_partial_refund_keeps_order_confirmed(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """A partial refund marks the payment partially_refunded but keeps the order."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    event_id, order_id = await _setup_pending_order(
        client, organizer, buyer, auth_headers
    )
    await _confirm_via_webhook(client, buyer, order_id, auth_headers, monkeypatch)

    resp = await client.post(
        f"{ORDERS_URL}/{order_id}/refund",
        headers=auth_headers(organizer),
        json={"amount": "25.00", "reason": "partial"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["payment_status"] == "partially_refunded"
    assert body["order_status"] == "confirmed"

    # Inventory remains held (2 tickets) for the still-confirmed order.
    avail = await client.get(f"{EVENTS_URL}/{event_id}/availability")
    assert avail.json()["tiers"][0]["quantity_sold"] == 2


async def test_webhook_bad_signature_exception_returns_400(
    client: AsyncClient, monkeypatch
) -> None:
    """A Stripe SignatureVerificationError surfaces as 400 (not 500)."""
    from stripe.error import SignatureVerificationError

    def _raise(payload, sig):
        raise SignatureVerificationError("bad sig", sig)

    monkeypatch.setattr(gateway_mod, "construct_event", _raise)
    resp = await client.post(
        WEBHOOK_URL, content=b"{}", headers={"stripe-signature": "bad"}
    )
    assert resp.status_code == 400


async def test_refund_non_admin_returns_403(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """A non-admin cannot refund an order."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    _, order_id = await _setup_pending_order(client, organizer, buyer, auth_headers)
    await _confirm_via_webhook(client, buyer, order_id, auth_headers, monkeypatch)

    resp = await client.post(
        f"{ORDERS_URL}/{order_id}/refund",
        headers=auth_headers(buyer),
        json={},
    )
    assert resp.status_code == 403


async def test_refund_without_payment_returns_400(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Refunding an order with no completed payment returns 400."""
    organizer = await make_user(email="org@example.com")
    buyer = await make_user(email="buyer@example.com")
    _, order_id = await _setup_pending_order(client, organizer, buyer, auth_headers)
    resp = await client.post(
        f"{ORDERS_URL}/{order_id}/refund",
        headers=auth_headers(organizer),
        json={},
    )
    assert resp.status_code == 400
