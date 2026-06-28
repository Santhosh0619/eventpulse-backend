"""Tests for the media feature: upload, list, delete, and reorder."""

import uuid
from io import BytesIO

from httpx import AsyncClient
from PIL import Image

ORGS_URL = "/api/v1/organizations"
EVENTS_URL = "/api/v1/events"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


def _png() -> bytes:
    """Return bytes of a small valid PNG image."""
    buf = BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, format="PNG")
    return buf.getvalue()


async def _setup_event(client: AsyncClient, headers: dict) -> str:
    """Create an org and an event, returning the event id."""
    org = await client.post(
        ORGS_URL,
        headers=headers,
        json={"name": "Media Org", "contact_email": "org@example.com"},
    )
    org_id = org.json()["id"]
    event = await client.post(
        EVENTS_URL,
        headers=headers,
        json={
            "organization_id": org_id,
            "title": "Media Event",
            "description": "x",
            "venue_name": "v",
            "start_datetime": START,
            "end_datetime": END,
        },
    )
    return event.json()["id"]


def _media_url(event_id: str) -> str:
    """Build the media collection URL for an event."""
    return f"{EVENTS_URL}/{event_id}/media"


async def _upload(client: AsyncClient, headers: dict, event_id: str):
    """Upload one PNG to the event and return the response."""
    files = {"file": ("pic.png", _png(), "image/png")}
    return await client.post(_media_url(event_id), headers=headers, files=files)


# --------------------------------------------------------------------------- #
# upload
# --------------------------------------------------------------------------- #


async def test_upload_media_success(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An org member can upload an image; a thumbnail is generated."""
    headers = auth_headers(verified_user)
    event_id = await _setup_event(client, headers)
    resp = await _upload(client, headers, event_id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["type"] == "image"
    assert body["url"].startswith("/uploads/events/originals/")
    assert body["thumbnail_url"] is not None


async def test_upload_media_requires_auth(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Uploading media without auth returns 401."""
    headers = auth_headers(verified_user)
    event_id = await _setup_event(client, headers)
    files = {"file": ("pic.png", _png(), "image/png")}
    resp = await client.post(_media_url(event_id), files=files)
    assert resp.status_code == 401


async def test_upload_media_non_member_returns_403(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A non-member cannot upload media to an event."""
    owner = await make_user(email="owner@example.com")
    outsider = await make_user(email="outsider@example.com")
    event_id = await _setup_event(client, auth_headers(owner))
    resp = await _upload(client, auth_headers(outsider), event_id)
    assert resp.status_code == 403


async def test_upload_media_bad_type_returns_400(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An unsupported media type is rejected with 400."""
    headers = auth_headers(verified_user)
    event_id = await _setup_event(client, headers)
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    resp = await client.post(_media_url(event_id), headers=headers, files=files)
    assert resp.status_code == 400


async def test_upload_media_spoofed_image_returns_400(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Non-image bytes labelled image/png are rejected by byte validation."""
    headers = auth_headers(verified_user)
    event_id = await _setup_event(client, headers)
    files = {"file": ("fake.png", b"not really an image", "image/png")}
    resp = await client.post(_media_url(event_id), headers=headers, files=files)
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# list / delete / reorder
# --------------------------------------------------------------------------- #


async def test_list_media_public(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Media listing is public and returns uploaded items."""
    headers = auth_headers(verified_user)
    event_id = await _setup_event(client, headers)
    await _upload(client, headers, event_id)
    resp = await client.get(_media_url(event_id))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_delete_media_success(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An org member can delete a media item."""
    headers = auth_headers(verified_user)
    event_id = await _setup_event(client, headers)
    media = (await _upload(client, headers, event_id)).json()
    resp = await client.delete(f"{_media_url(event_id)}/{media['id']}", headers=headers)
    assert resp.status_code == 204


async def test_delete_media_not_found_returns_404(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Deleting a non-existent media item returns 404."""
    headers = auth_headers(verified_user)
    event_id = await _setup_event(client, headers)
    resp = await client.delete(
        f"{_media_url(event_id)}/{uuid.uuid4()}", headers=headers
    )
    assert resp.status_code == 404


async def test_reorder_media(client: AsyncClient, verified_user, auth_headers) -> None:
    """Reordering media updates sort_order to match the supplied sequence."""
    headers = auth_headers(verified_user)
    event_id = await _setup_event(client, headers)
    first = (await _upload(client, headers, event_id)).json()
    second = (await _upload(client, headers, event_id)).json()

    resp = await client.put(
        f"{_media_url(event_id)}/reorder",
        headers=headers,
        json={"media_ids": [second["id"], first["id"]]},
    )
    assert resp.status_code == 200
    ordered = resp.json()
    assert ordered[0]["id"] == second["id"]
    assert ordered[1]["id"] == first["id"]


async def test_reorder_media_requires_membership(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A non-member cannot reorder media."""
    owner = await make_user(email="owner@example.com")
    outsider = await make_user(email="outsider@example.com")
    event_id = await _setup_event(client, auth_headers(owner))
    media = (await _upload(client, auth_headers(owner), event_id)).json()
    resp = await client.put(
        f"{_media_url(event_id)}/reorder",
        headers=auth_headers(outsider),
        json={"media_ids": [media["id"]]},
    )
    assert resp.status_code == 403
