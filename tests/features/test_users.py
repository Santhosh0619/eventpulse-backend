"""Tests for the users feature: profile read/update, public lookup, avatar upload."""

import uuid
from io import BytesIO

from httpx import AsyncClient
from PIL import Image

ME_URL = "/api/v1/users/me"
AVATAR_URL = "/api/v1/users/me/avatar"


def _valid_png_bytes() -> bytes:
    """Return the bytes of a minimal, genuinely valid PNG image."""
    buf = BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, format="PNG")
    return buf.getvalue()


def _users_url(user_id) -> str:
    """Build the public user-detail URL for a given id."""
    return f"/api/v1/users/{user_id}"


# --------------------------------------------------------------------------- #
# GET /users/me
# --------------------------------------------------------------------------- #


async def test_get_me_success(client: AsyncClient, verified_user, auth_headers) -> None:
    """An authenticated user can read their own account and profile."""
    resp = await client.get(ME_URL, headers=auth_headers(verified_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == verified_user.email
    assert body["profile"]["first_name"] == "Test"


async def test_get_me_without_auth_returns_401(client: AsyncClient) -> None:
    """Reading /users/me without a token returns 401."""
    resp = await client.get(ME_URL)
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# PUT /users/me
# --------------------------------------------------------------------------- #


async def test_update_me_success(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Updating profile fields persists and is reflected in the response."""
    resp = await client.put(
        ME_URL,
        headers=auth_headers(verified_user),
        json={"first_name": "Updated", "city": "Paris"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"]["first_name"] == "Updated"
    assert body["profile"]["city"] == "Paris"
    # Untouched field retains its original value.
    assert body["profile"]["last_name"] == "User"


async def test_update_me_without_auth_returns_401(client: AsyncClient) -> None:
    """Updating /users/me without a token returns 401."""
    resp = await client.put(ME_URL, json={"first_name": "X"})
    assert resp.status_code == 401


async def test_update_me_invalid_field_returns_422(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An empty first_name violates the min-length constraint (422)."""
    resp = await client.put(
        ME_URL,
        headers=auth_headers(verified_user),
        json={"first_name": ""},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# GET /users/{id}
# --------------------------------------------------------------------------- #


async def test_get_user_public_success(client: AsyncClient, verified_user) -> None:
    """Anyone can fetch a user's public profile (without email/account flags)."""
    resp = await client.get(_users_url(verified_user.id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(verified_user.id)
    assert body["profile"]["first_name"] == "Test"
    # Public view must not leak private fields.
    assert "email" not in body
    assert "is_verified" not in body


async def test_get_user_not_found_returns_404(client: AsyncClient) -> None:
    """Fetching a non-existent user id returns 404."""
    resp = await client.get(_users_url(uuid.uuid4()))
    assert resp.status_code == 404


async def test_get_user_invalid_uuid_returns_422(client: AsyncClient) -> None:
    """A malformed user id is rejected with 422."""
    resp = await client.get(_users_url("not-a-uuid"))
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# PUT /users/me/avatar
# --------------------------------------------------------------------------- #


async def test_upload_avatar_success(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Uploading a valid image sets and returns the avatar URL."""
    files = {"file": ("avatar.png", _valid_png_bytes(), "image/png")}
    resp = await client.put(
        AVATAR_URL, headers=auth_headers(verified_user), files=files
    )
    assert resp.status_code == 200
    assert resp.json()["avatar_url"].startswith("/uploads/avatars/")


async def test_upload_avatar_spoofed_content_returns_400(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """A non-image payload claiming image/png is rejected by byte validation."""
    files = {"file": ("avatar.png", b"this is not really a png", "image/png")}
    resp = await client.put(
        AVATAR_URL, headers=auth_headers(verified_user), files=files
    )
    assert resp.status_code == 400


async def test_upload_avatar_too_large_returns_400(
    client: AsyncClient, verified_user, auth_headers, monkeypatch
) -> None:
    """An upload exceeding the configured size limit is rejected with 400."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0)
    files = {"file": ("avatar.png", _valid_png_bytes(), "image/png")}
    resp = await client.put(
        AVATAR_URL, headers=auth_headers(verified_user), files=files
    )
    assert resp.status_code == 400


async def test_upload_avatar_invalid_type_returns_400(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Uploading a non-image file type is rejected with 400."""
    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    resp = await client.put(
        AVATAR_URL, headers=auth_headers(verified_user), files=files
    )
    assert resp.status_code == 400


async def test_upload_avatar_without_auth_returns_401(client: AsyncClient) -> None:
    """Uploading an avatar without a token returns 401."""
    files = {"file": ("avatar.png", b"\x89PNG\r\nfake", "image/png")}
    resp = await client.put(AVATAR_URL, files=files)
    assert resp.status_code == 401
