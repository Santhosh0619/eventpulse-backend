"""Tests for the liveness and readiness health endpoints."""

from httpx import AsyncClient

HEALTH_URL = "/api/v1/health"


async def test_liveness(client: AsyncClient) -> None:
    """The liveness probe always reports ok without checking dependencies."""
    resp = await client.get(HEALTH_URL)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_readiness_all_healthy(client: AsyncClient) -> None:
    """Readiness reports ok and 200 when the database and Redis are reachable."""
    resp = await client.get(f"{HEALTH_URL}/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"


async def test_readiness_degraded_returns_503(client: AsyncClient, monkeypatch) -> None:
    """Readiness returns 503 when a dependency (Redis) is unreachable."""

    class _BrokenRedis:
        async def ping(self):
            raise ConnectionError("redis down")

    import app.main as main_mod

    monkeypatch.setattr(main_mod, "get_redis", lambda: _BrokenRedis())

    resp = await client.get(f"{HEALTH_URL}/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] == "error"
    assert body["checks"]["database"] == "ok"
