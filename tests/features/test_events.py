"""Tests for the events feature: CRUD, search, lifecycle, and permissions."""

import uuid

from httpx import AsyncClient

EVENTS_URL = "/api/v1/events"
ORGS_URL = "/api/v1/organizations"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


async def _create_org(client: AsyncClient, headers: dict) -> str:
    """Create an organization and return its id."""
    resp = await client.post(
        ORGS_URL,
        headers=headers,
        json={"name": "Events Org", "contact_email": "org@example.com"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _event_payload(org_id: str, **over) -> dict:
    """Build a valid event-create payload."""
    payload = {
        "organization_id": org_id,
        "title": "Tech Summit",
        "description": "A great event.",
        "venue_name": "Convention Center",
        "city": "Bangalore",
        "start_datetime": START,
        "end_datetime": END,
        "tags": ["tech", "ai"],
    }
    payload.update(over)
    return payload


async def _create_event(client: AsyncClient, headers: dict, org_id: str, **over):
    """Create an event and return the response."""
    return await client.post(
        EVENTS_URL, headers=headers, json=_event_payload(org_id, **over)
    )


async def _add_member(client, owner_headers, org_id, member, member_headers, role):
    """Invite + accept a member into the org."""
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


async def test_create_event_success(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An org member can create a draft event with a generated slug."""
    headers = auth_headers(verified_user)
    org_id = await _create_org(client, headers)
    resp = await _create_event(client, headers, org_id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "draft"
    assert body["slug"] == "tech-summit"
    assert body["organization_id"] == org_id


async def test_create_event_requires_auth(client: AsyncClient) -> None:
    """Creating an event without auth returns 401."""
    resp = await client.post(EVENTS_URL, json=_event_payload(str(uuid.uuid4())))
    assert resp.status_code == 401


async def test_create_event_non_member_returns_403(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A non-member of the org cannot create an event for it."""
    owner = await make_user(email="owner@example.com")
    outsider = await make_user(email="outsider@example.com")
    org_id = await _create_org(client, auth_headers(owner))
    resp = await _create_event(client, auth_headers(outsider), org_id)
    assert resp.status_code == 403


async def test_create_event_bad_dates_returns_422(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """end_datetime not after start_datetime is rejected with 422."""
    headers = auth_headers(verified_user)
    org_id = await _create_org(client, headers)
    resp = await _create_event(
        client, headers, org_id, start_datetime=END, end_datetime=START
    )
    assert resp.status_code == 422


async def test_create_event_bad_category_returns_400(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """A non-existent category id is rejected with 400."""
    headers = auth_headers(verified_user)
    org_id = await _create_org(client, headers)
    resp = await _create_event(client, headers, org_id, category_id=str(uuid.uuid4()))
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# read / search
# --------------------------------------------------------------------------- #


async def test_get_event_success_and_not_found(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Events can be fetched by id; unknown ids return 404."""
    headers = auth_headers(verified_user)
    org_id = await _create_org(client, headers)
    event = (await _create_event(client, headers, org_id)).json()
    ok = await client.get(f"{EVENTS_URL}/{event['id']}")
    assert ok.status_code == 200
    missing = await client.get(f"{EVENTS_URL}/{uuid.uuid4()}")
    assert missing.status_code == 404


async def test_get_event_by_slug(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Events can be fetched by slug."""
    headers = auth_headers(verified_user)
    org_id = await _create_org(client, headers)
    event = (await _create_event(client, headers, org_id)).json()
    resp = await client.get(f"{EVENTS_URL}/slug/{event['slug']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == event["id"]


async def test_search_returns_only_published_by_default(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """The default search returns published events, not drafts."""
    headers = auth_headers(verified_user)
    org_id = await _create_org(client, headers)
    draft = (await _create_event(client, headers, org_id, title="Draft One")).json()
    published = (
        await _create_event(client, headers, org_id, title="Published One")
    ).json()
    await client.post(f"{EVENTS_URL}/{published['id']}/publish", headers=headers)

    resp = await client.get(EVENTS_URL)
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert published["id"] in ids
    assert draft["id"] not in ids
    assert body["total"] >= 1


async def test_search_filter_by_tag(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Searching by tag returns matching published events."""
    headers = auth_headers(verified_user)
    org_id = await _create_org(client, headers)
    ev = (await _create_event(client, headers, org_id, tags=["python", "web"])).json()
    await client.post(f"{EVENTS_URL}/{ev['id']}/publish", headers=headers)
    resp = await client.get(EVENTS_URL, params={"tags": "python"})
    assert resp.status_code == 200
    assert any(item["id"] == ev["id"] for item in resp.json()["items"])


async def test_featured_events(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """The featured endpoint returns published featured events."""
    resp = await client.get(f"{EVENTS_URL}/featured")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# --------------------------------------------------------------------------- #
# update / delete / lifecycle
# --------------------------------------------------------------------------- #


async def test_update_event_as_member(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A plain member can update an event."""
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    org_id = await _create_org(client, auth_headers(owner))
    await _add_member(
        client, auth_headers(owner), org_id, member, auth_headers(member), "member"
    )
    event = (await _create_event(client, auth_headers(owner), org_id)).json()
    resp = await client.put(
        f"{EVENTS_URL}/{event['id']}",
        headers=auth_headers(member),
        json={"title": "Renamed Summit"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Renamed Summit"


async def test_delete_event_requires_admin(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A plain member cannot delete an event (requires admin or owner)."""
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    org_id = await _create_org(client, auth_headers(owner))
    await _add_member(
        client, auth_headers(owner), org_id, member, auth_headers(member), "member"
    )
    event = (await _create_event(client, auth_headers(owner), org_id)).json()
    resp = await client.delete(
        f"{EVENTS_URL}/{event['id']}", headers=auth_headers(member)
    )
    assert resp.status_code == 403


async def test_delete_event_as_owner(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An owner can delete an event."""
    headers = auth_headers(verified_user)
    org_id = await _create_org(client, headers)
    event = (await _create_event(client, headers, org_id)).json()
    resp = await client.delete(f"{EVENTS_URL}/{event['id']}", headers=headers)
    assert resp.status_code == 204


async def test_publish_event_success(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An owner can publish a complete event."""
    headers = auth_headers(verified_user)
    org_id = await _create_org(client, headers)
    event = (await _create_event(client, headers, org_id)).json()
    resp = await client.post(f"{EVENTS_URL}/{event['id']}/publish", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"


async def test_publish_event_missing_fields_returns_400(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Publishing an event without description/venue returns 400."""
    headers = auth_headers(verified_user)
    org_id = await _create_org(client, headers)
    # Create minimal event without description or venue.
    resp = await client.post(
        EVENTS_URL,
        headers=headers,
        json={
            "organization_id": org_id,
            "title": "Bare Event",
            "start_datetime": START,
            "end_datetime": END,
        },
    )
    event = resp.json()
    pub = await client.post(f"{EVENTS_URL}/{event['id']}/publish", headers=headers)
    assert pub.status_code == 400


async def test_cancel_event_success(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An owner can cancel an event."""
    headers = auth_headers(verified_user)
    org_id = await _create_org(client, headers)
    event = (await _create_event(client, headers, org_id)).json()
    resp = await client.post(f"{EVENTS_URL}/{event['id']}/cancel", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
