"""Application middleware: security headers, body limits, CORS, request logging."""

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_413_REQUEST_ENTITY_TOO_LARGE

from app.core.config import settings

logger = logging.getLogger("eventpulse.request")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach standard security headers to every response."""

    # Swagger UI / ReDoc load assets from a CDN, so a strict CSP would break them.
    _CSP_EXEMPT_PATHS = ("/docs", "/redoc")

    async def dispatch(self, request: Request, call_next):
        """Add hardening headers after the response is produced."""
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if not request.url.path.startswith(self._CSP_EXEMPT_PATHS):
            headers.setdefault(
                "Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'"
            )
        headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        if settings.ENABLE_HSTS:
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared body exceeds the configured maximum."""

    async def dispatch(self, request: Request, call_next):
        """Short-circuit oversized requests via the Content-Length header."""
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                too_large = int(content_length) > settings.MAX_REQUEST_BODY_BYTES
            except ValueError:
                too_large = False
            if too_large:
                return JSONResponse(
                    status_code=HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"success": False, "message": "Request body too large"},
                )
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log each request's method, path, status code, and duration."""

    async def dispatch(self, request: Request, call_next):
        """Time the request and emit a structured log line."""
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


def setup_middleware(app: FastAPI) -> None:
    """Attach security, CORS, and request-logging middleware to the application.

    Starlette runs middleware in reverse order of registration, so the last one
    added wraps outermost. Body-size limiting is added last so it rejects
    oversized requests before any other middleware processes them.
    """
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(BodySizeLimitMiddleware)
