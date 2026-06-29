"""Recommendation scoring and orchestration.

Events are ranked by a weighted relevance score combining category match,
location match, price proximity, popularity, and average rating.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.features.events import services as events_services
from app.features.events.models import Event
from app.features.recommendations import crud
from app.features.recommendations.schemas import RecommendedEvent
from app.features.users.models import User

# Scoring weights (sum to 1.0).
_W_CATEGORY = 0.30
_W_LOCATION = 0.20
_W_PRICE = 0.15
_W_POPULARITY = 0.20
_W_RATING = 0.15

# Attendee count at which an event is considered maximally "popular".
_POPULARITY_CAP = 50.0
# Upper bound on events scored per request (performance guard).
_CANDIDATE_POOL = 500


def _price_score(min_price: Decimal | None, pref_price: Decimal | None) -> float:
    """Return a 0-1 closeness score between an event's price and a target price."""
    if pref_price is None or min_price is None:
        return 0.0
    target = float(pref_price)
    if target <= 0:
        return 1.0 if float(min_price) == 0 else 0.0
    diff = abs(float(min_price) - target) / target
    return max(0.0, 1.0 - diff)


def _score(
    event: Event,
    min_price: Decimal | None,
    popularity: int,
    avg_rating: float | None,
    pref_categories: set[uuid.UUID],
    pref_cities: set[str],
    pref_price: Decimal | None,
) -> float:
    """Compute an event's weighted relevance score in ``[0.0, 1.0]``."""
    category = (
        1.0 if event.category_id and event.category_id in pref_categories else 0.0
    )
    location = 1.0 if event.city and event.city in pref_cities else 0.0
    price = _price_score(min_price, pref_price)
    pop = min((popularity or 0) / _POPULARITY_CAP, 1.0)
    rating = float(avg_rating) / 5.0 if avg_rating is not None else 0.0
    total = (
        _W_CATEGORY * category
        + _W_LOCATION * location
        + _W_PRICE * price
        + _W_POPULARITY * pop
        + _W_RATING * rating
    )
    return round(total, 4)


async def _rank(
    db: AsyncSession,
    *,
    exclude_ids: set[uuid.UUID],
    pref_categories: set[uuid.UUID],
    pref_cities: set[str],
    pref_price: Decimal | None,
    limit: int,
) -> list[RecommendedEvent]:
    """Score the candidate pool and return the top ``limit`` events."""
    now = datetime.now(UTC)
    candidates = await crud.candidate_events(db, now, exclude_ids, _CANDIDATE_POOL)
    scored = [
        (
            row.Event,
            _score(
                row.Event,
                row.min_price,
                row.popularity,
                row.avg_rating,
                pref_categories,
                pref_cities,
                pref_price,
            ),
        )
        for row in candidates
    ]
    # Highest score first; ties broken by soonest start so ordering is stable.
    scored.sort(key=lambda s: (-s[1], s[0].start_datetime))
    return [
        RecommendedEvent(event=event, score=score) for event, score in scored[:limit]
    ]


async def get_personalized_recommendations(
    db: AsyncSession, user: User, limit: int = 10
) -> list[RecommendedEvent]:
    """Recommend upcoming events for a user based on their attendance history."""
    attended = await crud.user_attended_event_ids(db, user.id)
    return await _rank(
        db,
        exclude_ids=attended,
        pref_categories=await crud.user_pref_categories(db, user.id),
        pref_cities=await crud.user_pref_cities(db, user.id),
        pref_price=await crud.user_avg_price(db, user.id),
        limit=limit,
    )


async def get_similar_events(
    db: AsyncSession, event_id: uuid.UUID, limit: int = 10
) -> list[RecommendedEvent]:
    """Recommend events similar to a given event (public; no user context)."""
    source = await events_services.get_event(db, event_id)  # 404 if missing
    pref_categories = {source.category_id} if source.category_id else set()
    pref_cities = {source.city} if source.city else set()
    pref_price = await crud.event_min_price(db, event_id)
    return await _rank(
        db,
        exclude_ids={event_id},
        pref_categories=pref_categories,
        pref_cities=pref_cities,
        pref_price=pref_price,
        limit=limit,
    )
