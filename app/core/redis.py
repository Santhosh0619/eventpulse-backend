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


def _login_attempts_key(identifier: str) -> str:
    """Redis key tracking recent failed login attempts for an identifier."""
    return f"login:failed:{identifier.lower()}"


async def is_login_locked(identifier: str) -> bool:
    """Return whether an identifier (email) is currently locked out from login."""
    threshold = settings.LOGIN_MAX_FAILED_ATTEMPTS
    count = await get_redis().get(_login_attempts_key(identifier))
    return count is not None and int(count) >= threshold


async def record_failed_login(identifier: str) -> None:
    """Increment the failed-login counter for an identifier in the lockout window."""
    redis = get_redis()
    key = _login_attempts_key(identifier)
    count = await redis.incr(key)
    if count == 1:
        # First failure starts the sliding lockout window.
        await redis.expire(key, settings.LOGIN_LOCKOUT_SECONDS)


async def clear_failed_logins(identifier: str) -> None:
    """Reset the failed-login counter (called on a successful login)."""
    await get_redis().delete(_login_attempts_key(identifier))
