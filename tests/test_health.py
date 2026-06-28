"""Smoke tests for the health endpoint and application bootstrap."""

from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    """GET /api/v1/health returns status ok and the API version."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.0.0"
