"""Tests for the categories feature (public read, admin write)."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

CATEGORIES_URL = "/api/v1/categories"


async def _create(client: AsyncClient, admin_headers: dict, name: str = "Tech"):
    """Create a category as admin and return the response."""
    return await client.post(CATEGORIES_URL, headers=admin_headers, json={"name": name})


# --------------------------------------------------------------------------- #
# list (public)
# --------------------------------------------------------------------------- #


async def test_list_categories_public_empty(client: AsyncClient) -> None:
    """The category list is publicly readable and starts empty."""
    resp = await client.get(CATEGORIES_URL)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_categories_active_filter(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """The is_active query parameter filters the listing."""
    admin = await make_user(email="admin@example.com", role="admin")
    headers = auth_headers(admin)
    await client.post(
        CATEGORIES_URL, headers=headers, json={"name": "Active", "is_active": True}
    )
    await client.post(
        CATEGORIES_URL,
        headers=headers,
        json={"name": "Inactive", "is_active": False},
    )
    resp = await client.get(CATEGORIES_URL, params={"is_active": "true"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()}
    assert names == {"Active"}


# --------------------------------------------------------------------------- #
# create (admin)
# --------------------------------------------------------------------------- #


async def test_create_category_as_admin_success(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """An admin can create a category; the slug is generated from the name."""
    admin = await make_user(email="admin@example.com", role="admin")
    resp = await _create(client, auth_headers(admin), "Tech Conference")
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Tech Conference"
    assert body["slug"] == "tech-conference"


async def test_create_category_as_attendee_returns_403(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """A non-admin user cannot create a category."""
    resp = await _create(client, auth_headers(verified_user))
    assert resp.status_code == 403


async def test_create_category_without_auth_returns_401(
    client: AsyncClient,
) -> None:
    """Creating a category without auth returns 401."""
    resp = await client.post(CATEGORIES_URL, json={"name": "Tech"})
    assert resp.status_code == 401


async def test_create_category_duplicate_name_returns_409(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Creating a category with a duplicate name returns 409."""
    admin = await make_user(email="admin@example.com", role="admin")
    headers = auth_headers(admin)
    await _create(client, headers, "Music")
    resp = await _create(client, headers, "Music")
    assert resp.status_code == 409


async def test_create_category_missing_name_returns_422(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Creating a category without a name returns 422."""
    admin = await make_user(email="admin@example.com", role="admin")
    resp = await client.post(CATEGORIES_URL, headers=auth_headers(admin), json={})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# update / delete (admin)
# --------------------------------------------------------------------------- #


async def test_update_category_as_admin_success(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """An admin can update a category."""
    admin = await make_user(email="admin@example.com", role="admin")
    headers = auth_headers(admin)
    created = (await _create(client, headers, "Sports")).json()
    resp = await client.put(
        f"{CATEGORIES_URL}/{created['id']}",
        headers=headers,
        json={"is_active": False, "sort_order": 5},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    assert resp.json()["sort_order"] == 5


async def test_update_category_as_attendee_returns_403(
    client: AsyncClient, make_user, verified_user, auth_headers
) -> None:
    """A non-admin cannot update a category."""
    admin = await make_user(email="admin@example.com", role="admin")
    created = (await _create(client, auth_headers(admin), "Sports")).json()
    resp = await client.put(
        f"{CATEGORIES_URL}/{created['id']}",
        headers=auth_headers(verified_user),
        json={"is_active": False},
    )
    assert resp.status_code == 403


async def test_update_category_not_found_returns_404(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Updating a non-existent category returns 404."""
    admin = await make_user(email="admin@example.com", role="admin")
    resp = await client.put(
        f"{CATEGORIES_URL}/{uuid.uuid4()}",
        headers=auth_headers(admin),
        json={"is_active": False},
    )
    assert resp.status_code == 404


async def test_delete_category_as_admin_success(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """An admin can delete a category."""
    admin = await make_user(email="admin@example.com", role="admin")
    headers = auth_headers(admin)
    created = (await _create(client, headers, "Webinar")).json()
    resp = await client.delete(f"{CATEGORIES_URL}/{created['id']}", headers=headers)
    assert resp.status_code == 204


async def test_delete_category_as_attendee_returns_403(
    client: AsyncClient, make_user, verified_user, auth_headers
) -> None:
    """A non-admin cannot delete a category."""
    admin = await make_user(email="admin@example.com", role="admin")
    created = (await _create(client, auth_headers(admin), "Webinar")).json()
    resp = await client.delete(
        f"{CATEGORIES_URL}/{created['id']}", headers=auth_headers(verified_user)
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# seeding
# --------------------------------------------------------------------------- #


async def test_seed_default_categories(db_session: AsyncSession) -> None:
    """Seeding inserts the 10 default categories and is idempotent."""
    from app.features.categories.services import (
        DEFAULT_CATEGORIES,
        seed_default_categories,
    )

    added = await seed_default_categories(db_session)
    assert added == len(DEFAULT_CATEGORIES)
    # Running again adds nothing (idempotent).
    again = await seed_default_categories(db_session)
    assert again == 0
