"""Tests for security hardening: headers, body-size limit, and account lockout."""

from httpx import AsyncClient

LOGIN_URL = "/api/v1/auth/login"
HEALTH_URL = "/api/v1/health"


# --------------------------------------------------------------------------- #
# security headers
# --------------------------------------------------------------------------- #


async def test_security_headers_present(client: AsyncClient) -> None:
    """Every response carries the standard hardening headers."""
    resp = await client.get(HEALTH_URL)
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in resp.headers
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"


# --------------------------------------------------------------------------- #
# request body size limit
# --------------------------------------------------------------------------- #


async def test_oversized_body_rejected(client: AsyncClient, monkeypatch) -> None:
    """A request body over the configured cap is rejected with 413."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", 10)
    resp = await client.post(
        LOGIN_URL,
        json={"email": "someone@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 413
    assert resp.json()["message"] == "Request body too large"


async def test_normal_body_allowed(client: AsyncClient, make_user) -> None:
    """A normal-sized request body passes the size limit."""
    await make_user(email="ok@example.com", password="Password123!")
    resp = await client.post(
        LOGIN_URL, json={"email": "ok@example.com", "password": "Password123!"}
    )
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# account lockout
# --------------------------------------------------------------------------- #


async def test_account_lockout_after_failed_attempts(
    client: AsyncClient, make_user
) -> None:
    """After 10 failed logins the account locks, refusing even correct credentials."""
    await make_user(email="victim@example.com", password="Correct123!")

    for _ in range(10):
        resp = await client.post(
            LOGIN_URL, json={"email": "victim@example.com", "password": "Wrong123!"}
        )
        assert resp.status_code == 401

    # The account is now locked: even the correct password is refused with 403.
    locked = await client.post(
        LOGIN_URL, json={"email": "victim@example.com", "password": "Correct123!"}
    )
    assert locked.status_code == 403
    assert "locked" in locked.json()["message"].lower()


async def test_successful_login_resets_failed_counter(
    client: AsyncClient, make_user
) -> None:
    """A successful login clears prior failures so the account never locks."""
    await make_user(email="resilient@example.com", password="Correct123!")

    for _ in range(5):
        await client.post(
            LOGIN_URL,
            json={"email": "resilient@example.com", "password": "Wrong123!"},
        )
    # Succeed (clears the counter), then fail 9 more times — still under threshold.
    ok = await client.post(
        LOGIN_URL,
        json={"email": "resilient@example.com", "password": "Correct123!"},
    )
    assert ok.status_code == 200
    for _ in range(9):
        await client.post(
            LOGIN_URL,
            json={"email": "resilient@example.com", "password": "Wrong123!"},
        )
    still_ok = await client.post(
        LOGIN_URL,
        json={"email": "resilient@example.com", "password": "Correct123!"},
    )
    assert still_ok.status_code == 200
