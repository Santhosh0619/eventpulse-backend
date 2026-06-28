"""Async Redis client and helpers (used for refresh-token blacklisting)."""

from redis.asyncio import Redis, from_url

from app.core.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    """Return a lazily-initialized, shared async Redis client."""
    global _redis
    if _redis is None:
        _redis = from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def blacklist_token(jti: str, ttl_seconds: int) -> None:
    """Mark a token's JTI as revoked for ``ttl_seconds`` (its remaining lifetime)."""
    if ttl_seconds <= 0:
        return
    await get_redis().setex(f"blacklist:{jti}", ttl_seconds, "1")


async def is_token_blacklisted(jti: str) -> bool:
    """Return ``True`` if the given token JTI has been blacklisted."""
    return bool(await get_redis().exists(f"blacklist:{jti}"))
