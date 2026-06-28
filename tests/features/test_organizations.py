"""Tests for the organizations feature: CRUD, members, and invitations."""

import uuid

from httpx import AsyncClient

ORGS_URL = "/api/v1/organizations"
MY_ORGS_URL = "/api/v1/users/me/organizations"


async def _create_org(client: AsyncClient, headers: dict, name: str = "Acme Inc"):
    """Create an organization and return the response JSON."""
    resp = await client.post(
        ORGS_URL,
        headers=headers,
        json={"name": name, "contact_email": "org@example.com"},
    )
    assert resp.status_code == 201
    return resp.json()


async def _add_member(
    client: AsyncClient,
    owner_headers: dict,
    org_id: str,
    member,
    member_headers: dict,
    role: str = "member",
) -> dict:
    """Invite and accept a member, returning the membership JSON."""
    inv = await client.post(
        f"{ORGS_URL}/{org_id}/members/invite",
        headers=owner_headers,
        json={"email": member.email, "role": role},
    )
    assert inv.status_code == 201
    token = inv.json()["invitation_token"]
    acc = await client.post(
        f"{ORGS_URL}/invitations/{token}/accept", headers=member_headers
    )
    assert acc.status_code == 200
    return acc.json()


# --------------------------------------------------------------------------- #
# create / read
# --------------------------------------------------------------------------- #


async def test_create_org_success(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Creating an organization succeeds and slugifies the name."""
    resp = await client.post(
        ORGS_URL,
        headers=auth_headers(verified_user),
        json={"name": "My Cool Org", "contact_email": "org@example.com"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "My Cool Org"
    assert body["slug"] == "my-cool-org"
    assert body["created_by"] == str(verified_user.id)


async def test_create_org_requires_auth(client: AsyncClient) -> None:
    """Creating an organization without auth returns 401."""
    resp = await client.post(
        ORGS_URL, json={"name": "X", "contact_email": "x@example.com"}
    )
    assert resp.status_code == 401


async def test_create_org_invalid_email_returns_422(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An invalid contact_email is rejected with 422."""
    resp = await client.post(
        ORGS_URL,
        headers=auth_headers(verified_user),
        json={"name": "X", "contact_email": "not-an-email"},
    )
    assert resp.status_code == 422


async def test_create_org_makes_creator_owner(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """The creator appears as an owner in their organization list."""
    org = await _create_org(client, auth_headers(verified_user))
    resp = await client.get(MY_ORGS_URL, headers=auth_headers(verified_user))
    assert resp.status_code == 200
    orgs = resp.json()
    assert any(o["id"] == org["id"] and o["my_role"] == "owner" for o in orgs)


async def test_get_org_public_success(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Anyone can fetch an organization by id."""
    org = await _create_org(client, auth_headers(verified_user))
    resp = await client.get(f"{ORGS_URL}/{org['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == org["id"]


async def test_get_org_not_found_returns_404(client: AsyncClient) -> None:
    """Fetching an unknown organization id returns 404."""
    resp = await client.get(f"{ORGS_URL}/{uuid.uuid4()}")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# update / delete
# --------------------------------------------------------------------------- #


async def test_update_org_as_owner_success(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An owner can update their organization."""
    org = await _create_org(client, auth_headers(verified_user))
    resp = await client.put(
        f"{ORGS_URL}/{org['id']}",
        headers=auth_headers(verified_user),
        json={"description": "Updated description"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated description"


async def test_update_org_non_member_returns_403(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A non-member cannot update an organization."""
    owner = await make_user(email="owner@example.com")
    outsider = await make_user(email="outsider@example.com")
    org = await _create_org(client, auth_headers(owner))
    resp = await client.put(
        f"{ORGS_URL}/{org['id']}",
        headers=auth_headers(outsider),
        json={"description": "hacked"},
    )
    assert resp.status_code == 403


async def test_delete_org_as_owner_success(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An owner can delete their organization."""
    org = await _create_org(client, auth_headers(verified_user))
    resp = await client.delete(
        f"{ORGS_URL}/{org['id']}", headers=auth_headers(verified_user)
    )
    assert resp.status_code == 204
    gone = await client.get(f"{ORGS_URL}/{org['id']}")
    assert gone.status_code == 404


async def test_delete_org_as_admin_returns_403(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """An admin (non-owner) cannot delete the organization."""
    owner = await make_user(email="owner@example.com")
    admin = await make_user(email="admin@example.com")
    org = await _create_org(client, auth_headers(owner))
    await _add_member(
        client, auth_headers(owner), org["id"], admin, auth_headers(admin), "admin"
    )
    resp = await client.delete(f"{ORGS_URL}/{org['id']}", headers=auth_headers(admin))
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# invitations / members
# --------------------------------------------------------------------------- #


async def test_invite_and_accept_flow(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """An owner can invite a member who then accepts and joins."""
    owner = await make_user(email="owner@example.com")
    invitee = await make_user(email="invitee@example.com")
    org = await _create_org(client, auth_headers(owner))
    membership = await _add_member(
        client, auth_headers(owner), org["id"], invitee, auth_headers(invitee)
    )
    assert membership["user_id"] == str(invitee.id)
    assert membership["invitation_status"] == "accepted"


async def test_invite_requires_owner_or_admin(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A plain member cannot invite others."""
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    other = await make_user(email="other@example.com")
    org = await _create_org(client, auth_headers(owner))
    await _add_member(
        client, auth_headers(owner), org["id"], member, auth_headers(member)
    )
    resp = await client.post(
        f"{ORGS_URL}/{org['id']}/members/invite",
        headers=auth_headers(member),
        json={"email": other.email, "role": "member"},
    )
    assert resp.status_code == 403


async def test_invite_existing_member_returns_409(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Inviting someone who is already a member returns 409."""
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    org = await _create_org(client, auth_headers(owner))
    await _add_member(
        client, auth_headers(owner), org["id"], member, auth_headers(member)
    )
    resp = await client.post(
        f"{ORGS_URL}/{org['id']}/members/invite",
        headers=auth_headers(owner),
        json={"email": member.email, "role": "member"},
    )
    assert resp.status_code == 409


async def test_invite_duplicate_pending_returns_409(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A second pending invitation to the same email is rejected with 409."""
    owner = await make_user(email="owner@example.com")
    org = await _create_org(client, auth_headers(owner))
    first = await client.post(
        f"{ORGS_URL}/{org['id']}/members/invite",
        headers=auth_headers(owner),
        json={"email": "pending@example.com", "role": "member"},
    )
    assert first.status_code == 201
    second = await client.post(
        f"{ORGS_URL}/{org['id']}/members/invite",
        headers=auth_headers(owner),
        json={"email": "pending@example.com", "role": "member"},
    )
    assert second.status_code == 409


async def test_admin_cannot_remove_owner_returns_403(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """An admin cannot remove an owner from the organization."""
    owner = await make_user(email="owner@example.com")
    admin = await make_user(email="admin@example.com")
    org = await _create_org(client, auth_headers(owner))
    await _add_member(
        client, auth_headers(owner), org["id"], admin, auth_headers(admin), "admin"
    )
    resp = await client.delete(
        f"{ORGS_URL}/{org['id']}/members/{owner.id}",
        headers=auth_headers(admin),
    )
    assert resp.status_code == 403


async def test_accept_invitation_wrong_email_returns_403(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A user whose email differs from the invite cannot accept it."""
    owner = await make_user(email="owner@example.com")
    wrong = await make_user(email="wrong@example.com")
    org = await _create_org(client, auth_headers(owner))
    inv = await client.post(
        f"{ORGS_URL}/{org['id']}/members/invite",
        headers=auth_headers(owner),
        json={"email": "intended@example.com", "role": "member"},
    )
    token = inv.json()["invitation_token"]
    resp = await client.post(
        f"{ORGS_URL}/invitations/{token}/accept", headers=auth_headers(wrong)
    )
    assert resp.status_code == 403


async def test_accept_invitation_bad_token_returns_404(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Accepting with an unknown token returns 404."""
    resp = await client.post(
        f"{ORGS_URL}/invitations/bogus-token/accept",
        headers=auth_headers(verified_user),
    )
    assert resp.status_code == 404


async def test_list_members_as_member_success(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Any member can list the organization's members."""
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    org = await _create_org(client, auth_headers(owner))
    await _add_member(
        client, auth_headers(owner), org["id"], member, auth_headers(member)
    )
    resp = await client.get(
        f"{ORGS_URL}/{org['id']}/members", headers=auth_headers(member)
    )
    assert resp.status_code == 200
    roles = {m["role"] for m in resp.json()}
    assert "owner" in roles and "member" in roles


async def test_list_members_non_member_returns_403(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """A non-member cannot list members."""
    owner = await make_user(email="owner@example.com")
    outsider = await make_user(email="outsider@example.com")
    org = await _create_org(client, auth_headers(owner))
    resp = await client.get(
        f"{ORGS_URL}/{org['id']}/members", headers=auth_headers(outsider)
    )
    assert resp.status_code == 403


async def test_change_member_role_as_owner(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """An owner can promote a member to admin."""
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    org = await _create_org(client, auth_headers(owner))
    await _add_member(
        client, auth_headers(owner), org["id"], member, auth_headers(member)
    )
    resp = await client.put(
        f"{ORGS_URL}/{org['id']}/members/{member.id}/role",
        headers=auth_headers(owner),
        json={"role": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


async def test_remove_member_as_owner(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """An owner can remove a member."""
    owner = await make_user(email="owner@example.com")
    member = await make_user(email="member@example.com")
    org = await _create_org(client, auth_headers(owner))
    await _add_member(
        client, auth_headers(owner), org["id"], member, auth_headers(member)
    )
    resp = await client.delete(
        f"{ORGS_URL}/{org['id']}/members/{member.id}",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 204


async def test_cannot_remove_last_owner(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """The sole owner cannot be removed (org must keep an owner)."""
    org = await _create_org(client, auth_headers(verified_user))
    resp = await client.delete(
        f"{ORGS_URL}/{org['id']}/members/{verified_user.id}",
        headers=auth_headers(verified_user),
    )
    assert resp.status_code == 409
