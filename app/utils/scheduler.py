"""APScheduler job definitions and registration.

Jobs run against their own database session (independent of request sessions).
Registered jobs:
- ``cleanup_expired_orders`` every 60 seconds (Phase 5).
Event reminders (Phase 7) are added later.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.database import async_session_factory

logger = logging.getLogger("eventpulse.scheduler")

scheduler = AsyncIOScheduler()


async def _cleanup_expired_orders_job() -> None:
    """Scheduler job: cancel expired pending orders and release inventory."""
    from app.features.orders.services import cleanup_expired_orders

    try:
        async with async_session_factory() as session:
            count = await cleanup_expired_orders(session)
        if count:
            logger.info("Expired %s pending order(s)", count)
    except Exception:  # noqa: BLE001 - background job must never crash the loop
        logger.exception("cleanup_expired_orders job failed")


async def _event_reminders_job() -> None:
    """Scheduler job: notify attendees of events starting within 24 hours."""
    from app.features.notifications.services import dispatch_event_reminders

    try:
        async with async_session_factory() as session:
            count = await dispatch_event_reminders(session)
        if count:
            logger.info("Sent %s event reminder(s)", count)
    except Exception:  # noqa: BLE001 - background job must never crash the loop
        logger.exception("event_reminders job failed")


def register_jobs() -> None:
    """Register all recurring jobs on the scheduler."""
    scheduler.add_job(
        _cleanup_expired_orders_job,
        trigger="interval",
        seconds=60,
        id="cleanup_expired_orders",
        replace_existing=True,
    )
    scheduler.add_job(
        _event_reminders_job,
        trigger="cron",
        hour=9,
        minute=0,
        id="event_reminders",
        replace_existing=True,
    )


def start_scheduler() -> None:
    """Register jobs and start the background scheduler."""
    if not scheduler.running:
        register_jobs()
        scheduler.start()


def shutdown_scheduler() -> None:
    """Shut the scheduler down gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
