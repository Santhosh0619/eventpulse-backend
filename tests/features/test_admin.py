"""Tests for the admin feature: dashboard, management endpoints, audit logging."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

ADMIN_URL = "/api/v1/admin"
ORGS_URL = "/api/v1/organizations"
EVENTS_URL = "/api/v1/events"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


async def _make_org(client, organizer, auth_headers, name="Admin Org") -> str:
    """Create an organization and return its id."""
    resp = await client.post(
        ORGS_URL,
        headers=auth_headers(organizer),
        json={"name": name, "contact_email": "o@example.com"},
    )
    return resp.json()["id"]


async def _make_event(client, organizer, auth_headers, org_id) -> str:
    """Create a draft event and return its id."""
    resp = await client.post(
        EVENTS_URL,
        headers=auth_headers(organizer),
        json={
            "organization_id": org_id,
            "title": "Admin Event",
            "description": "d",
            "venue_name": "v",
            "start_datetime": START,
            "end_datetime": END,
        },
    )
    return resp.json()["id"]


async def _audit_actions(client, admin, auth_headers, **params) -> list[dict]:
    """Return audit-log items, optionally filtered (action/entity_type/user_id)."""
    resp = await client.get(
        f"{ADMIN_URL}/audit-logs", headers=auth_headers(admin), params=params
    )
    assert resp.status_code == 200
    return resp.json()["items"]


# --------------------------------------------------------------------------- #
# dashboard + auth
# --------------------------------------------------------------------------- #


async def test_dashboard_admin(client: AsyncClient, make_user, auth_headers) -> None:
    """An admin can read the dashboard counts."""
    admin = await make_user(email="admin@example.com", role="admin")
    resp = await client.get(f"{ADMIN_URL}/dashboard", headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_users"] >= 1
    assert "total_audit_logs" in body


async def test_dashboard_forbidden_for_non_admin(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """A non-admin is forbidden from the admin dashboard."""
    resp = await client.get(
        f"{ADMIN_URL}/dashboard", headers=auth_headers(verified_user)
    )
    assert resp.status_code == 403


async def test_admin_requires_auth(client: AsyncClient) -> None:
    """Admin endpoints require authentication."""
    resp = await client.get(f"{ADMIN_URL}/users")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# user management
# --------------------------------------------------------------------------- #


async def test_list_users_and_role_filter(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Listing users supports a role filter."""
    admin = await make_user(email="admin2@example.com", role="admin")
    await make_user(email="org2@example.com", role="organizer")

    resp = await client.get(
        f"{ADMIN_URL}/users?role=organizer", headers=auth_headers(admin)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert all(u["role"] == "organizer" for u in body["items"])


async def test_list_users_forbidden_for_non_admin(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """A non-admin cannot list users."""
    resp = await client.get(f"{ADMIN_URL}/users", headers=auth_headers(verified_user))
    assert resp.status_code == 403


async def test_update_user_role_is_audited(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Promoting a user changes their role and writes a role-change audit entry."""
    admin = await make_user(email="admin3@example.com", role="admin")
    target = await make_user(email="target@example.com", role="attendee")

    resp = await client.put(
        f"{ADMIN_URL}/users/{target.id}",
        headers=auth_headers(admin),
        json={"role": "organizer"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "organizer"

    logs = await _audit_actions(client, admin, auth_headers, action="user.role_changed")
    assert any(
        log["entity_id"] == str(target.id) and log["new_values"]["role"] == "organizer"
        for log in logs
    )


async def test_update_user_invalid_role_400(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """An unknown role is rejected."""
    admin = await make_user(email="admin4@example.com", role="admin")
    target = await make_user(email="target2@example.com")
    resp = await client.put(
        f"{ADMIN_URL}/users/{target.id}",
        headers=auth_headers(admin),
        json={"role": "superuser"},
    )
    assert resp.status_code == 400


async def test_update_user_not_found_404(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Updating an unknown user returns 404."""
    admin = await make_user(email="admin5@example.com", role="admin")
    resp = await client.put(
        f"{ADMIN_URL}/users/{uuid.uuid4()}",
        headers=auth_headers(admin),
        json={"is_active": False},
    )
    assert resp.status_code == 404


async def test_admin_cannot_self_demote_or_deactivate(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """An admin cannot strip their own admin role or deactivate themselves."""
    admin = await make_user(email="admin5b@example.com", role="admin")
    demote = await client.put(
        f"{ADMIN_URL}/users/{admin.id}",
        headers=auth_headers(admin),
        json={"role": "attendee"},
    )
    assert demote.status_code == 400
    deactivate = await client.put(
        f"{ADMIN_URL}/users/{admin.id}",
        headers=auth_headers(admin),
        json={"is_active": False},
    )
    assert deactivate.status_code == 400


# --------------------------------------------------------------------------- #
# organization + event management
# --------------------------------------------------------------------------- #


async def test_verify_organization_is_audited(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Verifying an org flips is_verified and writes an audit entry."""
    admin = await make_user(email="admin6@example.com", role="admin")
    organizer = await make_user(email="org6@example.com")
    org_id = await _make_org(client, organizer, auth_headers)

    resp = await client.put(
        f"{ADMIN_URL}/organizations/{org_id}/verify", headers=auth_headers(admin)
    )
    assert resp.status_code == 200
    assert resp.json()["is_verified"] is True

    logs = await _audit_actions(
        client, admin, auth_headers, action="organization.verified"
    )
    assert any(log["entity_id"] == org_id for log in logs)


async def test_feature_event_is_audited(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Featuring an event sets the flag and writes an audit entry."""
    admin = await make_user(email="admin7@example.com", role="admin")
    organizer = await make_user(email="org7@example.com")
    org_id = await _make_org(client, organizer, auth_headers)
    event_id = await _make_event(client, organizer, auth_headers, org_id)

    resp = await client.put(
        f"{ADMIN_URL}/events/{event_id}/feature",
        headers=auth_headers(admin),
        json={"is_featured": True},
    )
    assert resp.status_code == 200
    assert resp.json()["is_featured"] is True

    logs = await _audit_actions(client, admin, auth_headers, action="event.featured")
    assert any(log["entity_id"] == event_id for log in logs)


async def test_list_events_includes_drafts(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Admin event listing includes draft events (unlike the public search)."""
    admin = await make_user(email="admin8@example.com", role="admin")
    organizer = await make_user(email="org8@example.com")
    org_id = await _make_org(client, organizer, auth_headers)
    event_id = await _make_event(client, organizer, auth_headers, org_id)

    resp = await client.get(
        f"{ADMIN_URL}/events?status=draft", headers=auth_headers(admin)
    )
    assert resp.status_code == 200
    ids = [e["id"] for e in resp.json()["items"]]
    assert event_id in ids


# --------------------------------------------------------------------------- #
# audit logging wired into existing mutations
# --------------------------------------------------------------------------- #


async def test_event_creation_writes_audit_log(
    client: AsyncClient, make_user, auth_headers
) -> None:
    """Creating an event produces an event.created audit entry."""
    admin = await make_user(email="admin9@example.com", role="admin")
    organizer = await make_user(email="org9@example.com")
    org_id = await _make_org(client, organizer, auth_headers)
    event_id = await _make_event(client, organizer, auth_headers, org_id)

    logs = await _audit_actions(client, admin, auth_headers, action="event.created")
    entry = next((log for log in logs if log["entity_id"] == event_id), None)
    assert entry is not None
    assert entry["user_id"] == str(organizer.id)
    assert entry["entity_type"] == "event"


async def test_org_creation_and_invite_write_audit_logs(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession
) -> None:
    """Org creation and member invitation each produce audit entries."""
    admin = await make_user(email="admin10@example.com", role="admin")
    organizer = await make_user(email="org10@example.com")
    org_id = await _make_org(client, organizer, auth_headers)

    await client.post(
        f"{ORGS_URL}/{org_id}/members/invite",
        headers=auth_headers(organizer),
        json={"email": "invitee@example.com", "role": "member"},
    )

    created = await _audit_actions(
        client, admin, auth_headers, action="organization.created"
    )
    invited = await _audit_actions(client, admin, auth_headers, action="member.invited")
    assert any(log["entity_id"] == org_id for log in created)
    assert any(log["entity_id"] == org_id for log in invited)


async def test_audit_logs_forbidden_for_non_admin(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """A non-admin cannot view audit logs."""
    resp = await client.get(
        f"{ADMIN_URL}/audit-logs", headers=auth_headers(verified_user)
    )
    assert resp.status_code == 403
