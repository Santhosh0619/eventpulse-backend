"""Application rate limiting via slowapi, backed by Redis.

Limits are bucketed per identity: an authenticated caller is keyed by a hash of
their bearer token, anonymous callers by client IP. A Redis storage backend keeps
counts shared across worker processes. All endpoints inherit ``RATE_LIMIT_DEFAULT``;
auth and webhook endpoints set stricter explicit limits via ``@limiter.limit``.
"""

import hashlib

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings


def _client_ip(request: Request) -> str:
    """Resolve the client IP, honoring X-Forwarded-For only behind a trusted proxy."""
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # The left-most entry is the original client (set by the trusted proxy).
            return forwarded.split(",")[0].strip()
    return get_remote_address(request)


def identity_key(request: Request) -> str:
    """Return the rate-limit bucket: a token hash if authenticated, else client IP."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer ") and len(auth) > 7:
        token_hash = hashlib.sha256(auth[7:].encode()).hexdigest()[:24]
        return f"user:{token_hash}"
    return f"ip:{_client_ip(request)}"


# ``swallow_errors`` keeps a Redis outage from 500-ing every request: rate limiting
# fails open (requests proceed) rather than taking the whole API down.
limiter = Limiter(
    key_func=identity_key,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    storage_uri=settings.REDIS_URL,
    headers_enabled=True,
    enabled=settings.RATE_LIMIT_ENABLED,
    strategy="fixed-window",
    swallow_errors=True,
)
