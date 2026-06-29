"""Redis-backed JSON caching with TTLs and prefix invalidation.

All operations are best-effort: any Redis failure is logged and treated as a
cache miss so the application degrades gracefully to the database rather than
erroring. Values are stored as JSON (``default=str`` handles UUID/Decimal/datetime).
"""

import json
import logging

from app.core.redis import get_redis

logger = logging.getLogger("eventpulse.cache")

# Time-to-live, in seconds, per cached resource.
TTL_EVENT_LIST = 300  # event listings: 5 minutes
TTL_AVAILABILITY = 30  # ticket availability: 30 seconds
TTL_RECOMMENDATIONS = 3600  # recommendations: 1 hour
TTL_REVIEW_SUMMARY = 600  # review summaries: 10 minutes

# Key prefixes (also used as invalidation prefixes).
EVENT_LIST_PREFIX = "events:list:"
AVAILABILITY_PREFIX = "tickets:availability:"
REVIEW_SUMMARY_PREFIX = "reviews:summary:"
RECOMMENDATIONS_PREFIX = "recommendations:"


async def get_json(key: str):
    """Return the cached JSON value for ``key``, or ``None`` on miss/error."""
    try:
        raw = await get_redis().get(key)
    except Exception:  # noqa: BLE001 - cache is best-effort
        logger.warning("cache get failed for key %s", key, exc_info=True)
        return None
    return json.loads(raw) if raw is not None else None


async def set_json(key: str, value, ttl: int) -> None:
    """Store ``value`` as JSON under ``key`` with a ``ttl``-second expiry."""
    try:
        await get_redis().setex(key, ttl, json.dumps(value, default=str))
    except Exception:  # noqa: BLE001 - cache is best-effort
        logger.warning("cache set failed for key %s", key, exc_info=True)


async def delete(*keys: str) -> None:
    """Delete one or more exact cache keys."""
    if not keys:
        return
    try:
        await get_redis().delete(*keys)
    except Exception:  # noqa: BLE001 - cache is best-effort
        logger.warning("cache delete failed for keys %s", keys, exc_info=True)


async def invalidate_prefix(prefix: str) -> None:
    """Delete every key beginning with ``prefix`` (uses non-blocking SCAN)."""
    try:
        redis = get_redis()
        keys = [key async for key in redis.scan_iter(match=f"{prefix}*", count=100)]
        if keys:
            await redis.delete(*keys)
    except Exception:  # noqa: BLE001 - cache is best-effort
        logger.warning("cache invalidate failed for prefix %s", prefix, exc_info=True)
