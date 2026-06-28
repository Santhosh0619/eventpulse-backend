"""Concurrency test: ticket overselling must be impossible under load.

Unlike the savepoint-isolated fixtures in conftest, this test uses real,
independent database sessions/connections so the ``SELECT ... FOR UPDATE`` row
lock in ``atomic_reserve`` is genuinely exercised under contention.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import BadRequestError
from app.core.security import hash_password
from app.features.events.models import Event
from app.features.orders.models import Order
from app.features.orders.services import place_order
from app.features.organizations.models import Organization
from app.features.tickets.models import TicketType
from app.features.users.models import User, UserProfile
from tests.conftest import TEST_DATABASE_URL

CAPACITY = 5
CONCURRENT_ATTEMPTS = 100


@pytest.mark.asyncio
async def test_concurrent_orders_never_oversell() -> None:
    """100 simultaneous single-ticket orders against 5 seats → exactly 5 succeed."""
    engine = create_async_engine(TEST_DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    suffix = uuid.uuid4().hex[:8]
    async with session_factory() as s:
        user = User(
            email=f"buyer-{suffix}@example.com",
            password_hash=hash_password("Password123!"),
            is_verified=True,
            profile=UserProfile(first_name="Buyer", last_name="One"),
        )
        org = Organization(
            name=f"Conc Org {suffix}",
            slug=f"conc-org-{suffix}",
            contact_email="o@example.com",
        )
        s.add_all([user, org])
        await s.commit()
        event = Event(
            organization_id=org.id,
            title=f"Conc Event {suffix}",
            slug=f"conc-event-{suffix}",
            description="d",
            venue_name="v",
            start_datetime=datetime(2030, 6, 1, 10, tzinfo=UTC),
            end_datetime=datetime(2030, 6, 1, 18, tzinfo=UTC),
            status="published",
        )
        s.add(event)
        await s.commit()
        tier = TicketType(
            event_id=event.id,
            name="GA",
            price=10,
            quantity_total=CAPACITY,
            max_per_order=10,
            is_active=True,
        )
        s.add(tier)
        await s.commit()
        user_id, org_id = user.id, org.id
        event_id, tier_id = event.id, tier.id

    async def attempt() -> bool:
        """Try to buy one ticket in an independent session/transaction."""
        async with session_factory() as session:
            buyer = await session.get(User, user_id)
            try:
                await place_order(
                    session,
                    buyer,
                    {
                        "event_id": event_id,
                        "items": [{"ticket_type_id": tier_id, "quantity": 1}],
                        "notes": None,
                    },
                )
                return True
            except BadRequestError:
                return False

    results = await asyncio.gather(*(attempt() for _ in range(CONCURRENT_ATTEMPTS)))

    try:
        assert sum(results) == CAPACITY, f"expected {CAPACITY} successes"
        async with session_factory() as s:
            final_tier = await s.get(TicketType, tier_id)
            assert final_tier.quantity_sold == CAPACITY
    finally:
        # Clean up the committed rows so the shared test DB stays tidy.
        async with session_factory() as s:
            await s.execute(delete(Order).where(Order.event_id == event_id))
            await s.execute(delete(TicketType).where(TicketType.id == tier_id))
            await s.execute(delete(Event).where(Event.id == event_id))
            await s.execute(delete(Organization).where(Organization.id == org_id))
            await s.execute(delete(User).where(User.id == user_id))
            await s.commit()
        await engine.dispose()
