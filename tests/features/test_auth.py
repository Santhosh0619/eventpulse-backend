"""Tests for the auth feature: register, login, refresh, email/password, logout."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.features.users.models import User

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
VERIFY_URL = "/api/v1/auth/verify-email"
FORGOT_URL = "/api/v1/auth/forgot-password"
RESET_URL = "/api/v1/auth/reset-password"
LOGOUT_URL = "/api/v1/auth/logout"

VALID_PASSWORD = "Password123!"


def _register_payload(**overrides) -> dict:
    """Build a valid registration payload, applying any overrides."""
    payload = {
        "email": "newuser@example.com",
        "password": VALID_PASSWORD,
        "first_name": "New",
        "last_name": "User",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# register
# --------------------------------------------------------------------------- #


async def test_register_success(client: AsyncClient) -> None:
    """Registering with valid data returns 201 and a safe user representation."""
    resp = await client.post(REGISTER_URL, json=_register_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "newuser@example.com"
    assert body["role"] == "attendee"
    assert body["is_verified"] is False
    assert body["is_active"] is True
    # Sensitive fields must never be serialized.
    assert "password_hash" not in body
    assert "password" not in body


async def test_register_persists_user_and_profile(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Registration creates both the user and its linked profile."""
    await client.post(REGISTER_URL, json=_register_payload())
    user = (
        await db_session.execute(
            select(User)
            .where(User.email == "newuser@example.com")
            .options(selectinload(User.profile))
        )
    ).scalar_one()
    assert user.verification_token is not None
    assert user.profile is not None
    assert user.profile.first_name == "New"


async def test_register_duplicate_email_returns_409(
    client: AsyncClient, make_user
) -> None:
    """Registering an already-used email returns 409 Conflict."""
    await make_user(email="taken@example.com")
    resp = await client.post(
        REGISTER_URL, json=_register_payload(email="taken@example.com")
    )
    assert resp.status_code == 409


async def test_register_short_password_returns_422(client: AsyncClient) -> None:
    """A password shorter than the minimum length is rejected with 422."""
    resp = await client.post(REGISTER_URL, json=_register_payload(password="short"))
    assert resp.status_code == 422


async def test_register_invalid_email_returns_422(client: AsyncClient) -> None:
    """A malformed email is rejected with 422."""
    resp = await client.post(REGISTER_URL, json=_register_payload(email="not-an-email"))
    assert resp.status_code == 422


async def test_register_missing_fields_returns_422(client: AsyncClient) -> None:
    """Missing required fields are rejected with 422."""
    resp = await client.post(REGISTER_URL, json={"email": "a@example.com"})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# login
# --------------------------------------------------------------------------- #


async def test_login_success(client: AsyncClient, make_user) -> None:
    """A verified user can log in and receive an access + refresh token pair."""
    await make_user(email="login@example.com", password=VALID_PASSWORD)
    resp = await client.post(
        LOGIN_URL, json={"email": "login@example.com", "password": VALID_PASSWORD}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


async def test_login_wrong_password_returns_401(client: AsyncClient, make_user) -> None:
    """Logging in with the wrong password returns 401."""
    await make_user(email="login@example.com", password=VALID_PASSWORD)
    resp = await client.post(
        LOGIN_URL, json={"email": "login@example.com", "password": "WrongPass1!"}
    )
    assert resp.status_code == 401


async def test_login_unknown_email_returns_401(client: AsyncClient) -> None:
    """Logging in with an unknown email returns 401 (no user enumeration)."""
    resp = await client.post(
        LOGIN_URL, json={"email": "ghost@example.com", "password": VALID_PASSWORD}
    )
    assert resp.status_code == 401


async def test_login_unverified_returns_403(client: AsyncClient, make_user) -> None:
    """An unverified account cannot log in (403)."""
    await make_user(email="unverified@example.com", is_verified=False)
    resp = await client.post(
        LOGIN_URL,
        json={"email": "unverified@example.com", "password": VALID_PASSWORD},
    )
    assert resp.status_code == 403


async def test_login_inactive_returns_403(client: AsyncClient, make_user) -> None:
    """A deactivated account cannot log in (403)."""
    await make_user(email="inactive@example.com", is_active=False)
    resp = await client.post(
        LOGIN_URL,
        json={"email": "inactive@example.com", "password": VALID_PASSWORD},
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# refresh
# --------------------------------------------------------------------------- #


async def _login(client: AsyncClient, email: str) -> dict:
    """Helper: log in and return the token pair."""
    resp = await client.post(
        LOGIN_URL, json={"email": email, "password": VALID_PASSWORD}
    )
    assert resp.status_code == 200
    return resp.json()


async def test_refresh_success(client: AsyncClient, make_user) -> None:
    """A valid refresh token yields a new token pair."""
    await make_user(email="refresh@example.com")
    tokens = await _login(client, "refresh@example.com")
    resp = await client.post(
        REFRESH_URL, json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]


async def test_refresh_invalid_token_returns_401(client: AsyncClient) -> None:
    """A garbage refresh token is rejected with 401."""
    resp = await client.post(REFRESH_URL, json={"refresh_token": "not.a.jwt"})
    assert resp.status_code == 401


async def test_refresh_with_access_token_returns_401(
    client: AsyncClient, make_user
) -> None:
    """Presenting an access token to the refresh endpoint is rejected (wrong type)."""
    await make_user(email="refresh2@example.com")
    tokens = await _login(client, "refresh2@example.com")
    resp = await client.post(
        REFRESH_URL, json={"refresh_token": tokens["access_token"]}
    )
    assert resp.status_code == 401


async def test_refresh_rotated_token_is_blacklisted(
    client: AsyncClient, make_user
) -> None:
    """After rotation, the old refresh token can no longer be used (401)."""
    await make_user(email="rotate@example.com")
    tokens = await _login(client, "rotate@example.com")
    old_refresh = tokens["refresh_token"]
    first = await client.post(REFRESH_URL, json={"refresh_token": old_refresh})
    assert first.status_code == 200
    reused = await client.post(REFRESH_URL, json={"refresh_token": old_refresh})
    assert reused.status_code == 401


# --------------------------------------------------------------------------- #
# verify-email
# --------------------------------------------------------------------------- #


async def test_verify_email_success(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """A valid verification token marks the account verified and clears the token."""
    await client.post(REGISTER_URL, json=_register_payload(email="verify@example.com"))
    user = (
        await db_session.execute(select(User).where(User.email == "verify@example.com"))
    ).scalar_one()
    token = user.verification_token

    resp = await client.post(VERIFY_URL, json={"token": token})
    assert resp.status_code == 200

    await db_session.refresh(user)
    assert user.is_verified is True
    assert user.verification_token is None


async def test_verify_email_invalid_token_returns_400(client: AsyncClient) -> None:
    """An unknown verification token returns 400."""
    resp = await client.post(VERIFY_URL, json={"token": "bogus-token"})
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# forgot-password / reset-password
# --------------------------------------------------------------------------- #


async def test_forgot_password_existing_email_sets_token(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """Requesting a reset for a real account stores a reset token + expiry."""
    user = await make_user(email="forgot@example.com")
    resp = await client.post(FORGOT_URL, json={"email": "forgot@example.com"})
    assert resp.status_code == 200
    await db_session.refresh(user)
    assert user.password_reset_token is not None
    assert user.password_reset_expires is not None


async def test_forgot_password_unknown_email_returns_200(client: AsyncClient) -> None:
    """Requesting a reset for an unknown email still returns 200 (no enumeration)."""
    resp = await client.post(FORGOT_URL, json={"email": "nobody@example.com"})
    assert resp.status_code == 200


async def test_reset_password_success(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """A valid reset token lets the user set a new password and log in with it."""
    user = await make_user(email="reset@example.com")
    await client.post(FORGOT_URL, json={"email": "reset@example.com"})
    await db_session.refresh(user)
    token = user.password_reset_token

    new_password = "BrandNewPass9!"
    resp = await client.post(
        RESET_URL, json={"token": token, "new_password": new_password}
    )
    assert resp.status_code == 200

    login = await client.post(
        LOGIN_URL, json={"email": "reset@example.com", "password": new_password}
    )
    assert login.status_code == 200


async def test_reset_password_invalid_token_returns_400(client: AsyncClient) -> None:
    """An unknown reset token returns 400."""
    resp = await client.post(
        RESET_URL, json={"token": "bogus", "new_password": "BrandNewPass9!"}
    )
    assert resp.status_code == 400


async def test_reset_password_short_password_returns_422(client: AsyncClient) -> None:
    """A too-short new password is rejected with 422."""
    resp = await client.post(
        RESET_URL, json={"token": "whatever", "new_password": "short"}
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# logout
# --------------------------------------------------------------------------- #


async def test_logout_success(client: AsyncClient, make_user) -> None:
    """A logged-in user can log out, revoking the refresh token."""
    await make_user(email="logout@example.com")
    tokens = await _login(client, "logout@example.com")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    resp = await client.post(
        LOGOUT_URL,
        json={"refresh_token": tokens["refresh_token"]},
        headers=headers,
    )
    assert resp.status_code == 200

    # The revoked refresh token can no longer be used.
    reused = await client.post(
        REFRESH_URL, json={"refresh_token": tokens["refresh_token"]}
    )
    assert reused.status_code == 401


async def test_logout_without_auth_returns_401(client: AsyncClient) -> None:
    """Logout requires a valid access token."""
    resp = await client.post(LOGOUT_URL, json={"refresh_token": "anything"})
    assert resp.status_code == 401


async def test_logout_does_not_revoke_another_users_token(
    client: AsyncClient, make_user
) -> None:
    """A user cannot revoke a refresh token that belongs to someone else."""
    await make_user(email="attacker@example.com")
    await make_user(email="victim@example.com")
    attacker = await _login(client, "attacker@example.com")
    victim = await _login(client, "victim@example.com")

    # Attacker (authenticated) submits the victim's refresh token to logout.
    headers = {"Authorization": f"Bearer {attacker['access_token']}"}
    resp = await client.post(
        LOGOUT_URL,
        json={"refresh_token": victim["refresh_token"]},
        headers=headers,
    )
    assert resp.status_code == 200

    # The victim's refresh token must still be usable.
    still_valid = await client.post(
        REFRESH_URL, json={"refresh_token": victim["refresh_token"]}
    )
    assert still_valid.status_code == 200


async def test_reset_password_expired_token_returns_400(
    client: AsyncClient, make_user, db_session: AsyncSession
) -> None:
    """An expired password-reset token is rejected with 400."""
    user = await make_user(email="expired@example.com")
    user.password_reset_token = "expired-token"
    user.password_reset_expires = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()

    resp = await client.post(
        RESET_URL,
        json={"token": "expired-token", "new_password": "BrandNewPass9!"},
    )
    assert resp.status_code == 400
