"""Tests for slowapi rate limiting (default, auth, and webhook limits)."""

import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
def _enable_rate_limit():
    """Enable the limiter for a test (the suite disables it by default)."""
    from app.core.rate_limit import limiter

    limiter.enabled = True
    yield
    limiter.enabled = False


async def test_auth_endpoint_rate_limited(
    client: AsyncClient, _enable_rate_limit
) -> None:
    """The login endpoint allows 5 requests/min per IP, then returns 429."""
    payload = {"email": "nobody@example.com", "password": "Wrongpass123!"}
    statuses = []
    for _ in range(6):
        resp = await client.post("/api/v1/auth/login", json=payload)
        statuses.append(resp.status_code)

    # First 5 are processed (401 invalid credentials); the 6th is rate limited.
    assert statuses[:5] == [401, 401, 401, 401, 401]
    assert statuses[5] == 429


async def test_default_limit_allows_normal_traffic(
    client: AsyncClient, _enable_rate_limit
) -> None:
    """A non-auth endpoint tolerates well under the 100/min default limit."""
    for _ in range(10):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200


async def test_rate_limit_disabled_by_default(client: AsyncClient) -> None:
    """With the limiter disabled (suite default), many auth calls are not blocked."""
    payload = {"email": "nobody2@example.com", "password": "Wrongpass123!"}
    for _ in range(8):
        resp = await client.post("/api/v1/auth/login", json=payload)
        assert resp.status_code == 401
