"""APScheduler job definitions.

Placeholder for Phase 0. Jobs (order expiry in Phase 5, event reminders in
Phase 7) are registered against this scheduler and started from the app lifespan.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    """Start the background scheduler if it is not already running."""
    if not scheduler.running:
        scheduler.start()


def shutdown_scheduler() -> None:
    """Shut the scheduler down gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
