"""FastAPI application factory, router registration, and lifespan events."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.dependencies import DBSession
from app.core.exceptions import register_exception_handlers
from app.core.middleware import setup_middleware
from app.core.rate_limit import limiter
from app.core.redis import get_redis

# Feature routers
from app.features.admin.router import router as admin_router
from app.features.analytics.router import router as analytics_router
from app.features.attendees.router import router as attendees_router
from app.features.auth.router import router as auth_router
from app.features.categories.router import router as categories_router
from app.features.events.router import router as events_router
from app.features.events.ws import router as events_ws_router
from app.features.media.router import router as media_router
from app.features.notifications.router import router as notifications_router
from app.features.orders.router import router as orders_router
from app.features.orders.router import user_orders_router
from app.features.organizations.router import router as orgs_router
from app.features.organizations.router import user_orgs_router
from app.features.payments.router import router as payments_router
from app.features.recommendations.router import router as recommendations_router
from app.features.reviews.router import router as reviews_router
from app.features.tickets.router import router as tickets_router
from app.features.users.router import router as users_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan: ensure upload dirs and run the background scheduler."""
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    from app.utils.scheduler import shutdown_scheduler, start_scheduler

    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="EventPulse — event management and ticketing platform API.",
        lifespan=lifespan,
        debug=settings.DEBUG,
    )

    # Rate limiting: register the limiter, its 429 handler, and middleware. The
    # SlowAPIMiddleware applies the default limit to every route; specific routes
    # tighten it with their own @limiter.limit decorators.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    setup_middleware(app)
    register_exception_handlers(app)

    # Serve locally-stored uploads (avatars, logos, event media, QR codes).
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    app.mount(
        settings.SERVE_UPLOADS_URL,
        StaticFiles(directory=settings.UPLOAD_DIR),
        name="uploads",
    )

    @app.get("/api/v1/health", tags=["Health"], summary="Liveness probe")
    async def health() -> dict[str, str]:
        """Liveness probe: confirms the process is up (no dependency checks)."""
        return {"status": "ok", "version": "1.0.0"}

    @app.get("/api/v1/health/ready", tags=["Health"], summary="Readiness probe")
    async def readiness(db: DBSession, response: Response) -> dict:
        """Readiness probe: verifies the database and Redis are reachable.

        Returns 200 when all dependencies are healthy, else 503 so load balancers
        and uptime monitors can route around an unhealthy instance.
        """
        checks: dict[str, str] = {}
        try:
            await db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:  # noqa: BLE001 - report failure, don't propagate
            checks["database"] = "error"
        try:
            await get_redis().ping()
            checks["redis"] = "ok"
        except Exception:  # noqa: BLE001 - report failure, don't propagate
            checks["redis"] = "error"

        healthy = all(v == "ok" for v in checks.values())
        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ok" if healthy else "degraded",
            "version": "1.0.0",
            "checks": checks,
        }

    _register_routers(app)
    return app


def _register_routers(app: FastAPI) -> None:
    """Register every feature router under its API prefix and tag."""
    p = settings.API_V1_PREFIX
    app.include_router(auth_router, prefix=f"{p}/auth", tags=["Auth"])
    app.include_router(users_router, prefix=f"{p}/users", tags=["Users"])
    app.include_router(orgs_router, prefix=f"{p}/organizations", tags=["Organizations"])
    # Organization route that lives under the /users path.
    app.include_router(user_orgs_router, prefix=f"{p}/users", tags=["Organizations"])
    app.include_router(categories_router, prefix=f"{p}/categories", tags=["Categories"])
    app.include_router(events_router, prefix=f"{p}/events", tags=["Events"])
    # WebSocket for live attendee counts: /api/v1/ws/events/{event_id}
    app.include_router(events_ws_router, prefix=p, tags=["Events"])
    app.include_router(media_router, prefix=p, tags=["Media"])
    app.include_router(tickets_router, prefix=p, tags=["Tickets"])
    app.include_router(orders_router, prefix=p, tags=["Orders"])
    app.include_router(user_orders_router, prefix=f"{p}/users", tags=["Orders"])
    app.include_router(payments_router, prefix=p, tags=["Payments"])
    app.include_router(attendees_router, prefix=p, tags=["Attendees"])
    app.include_router(reviews_router, prefix=p, tags=["Reviews"])
    app.include_router(
        notifications_router, prefix=f"{p}/notifications", tags=["Notifications"]
    )
    app.include_router(analytics_router, prefix=f"{p}/analytics", tags=["Analytics"])
    app.include_router(
        recommendations_router,
        prefix=f"{p}/recommendations",
        tags=["Recommendations"],
    )
    app.include_router(admin_router, prefix=f"{p}/admin", tags=["Admin"])


app = create_app()
