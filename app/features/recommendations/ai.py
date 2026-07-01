"""AI-powered recommendations using Google Gemini.

Layers Gemini 2.0 Flash on top of the heuristic candidate pool: the model
receives a summary of the user's booking history plus a compact list of
candidate events, then returns a curated, ranked selection with a short reason
for each pick.

Every entry point degrades gracefully — if Gemini is unconfigured, rate-limited,
returns malformed output, or errors, the endpoint falls back to the existing
heuristic ranking so the feature always returns useful results.
"""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cache
from app.core.gemini import GeminiClient, GeminiError, get_gemini
from app.features.events import services as events_services
from app.features.events.models import Event
from app.features.recommendations import crud, services
from app.features.recommendations.schemas import AiRecommendedEvent, RecommendedEvent
from app.features.users.models import User

# Candidate events sent to the model per request. Kept small so the prompt stays
# well within free-tier limits while giving the model enough to choose from.
_AI_CANDIDATE_POOL = 40
# Recent attended events summarised as taste context.
_HISTORY_LIMIT = 8
# Cache AI results for the same TTL as heuristic recommendations (1 hour).
_AI_USER_PREFIX = f"{cache.RECOMMENDATIONS_PREFIX}ai:user:"
_AI_SIMILAR_PREFIX = f"{cache.RECOMMENDATIONS_PREFIX}ai:similar:"


def _event_brief(
    event: Event,
    min_price: Decimal | None = None,
    popularity: int | None = None,
    rating: float | None = None,
) -> dict:
    """Return a compact, prompt-friendly summary of an event."""
    brief: dict = {
        "id": str(event.id),
        "title": event.title,
        "city": event.city,
        "tags": (event.tags or [])[:6],
    }
    if event.short_description:
        brief["summary"] = event.short_description[:160]
    if min_price is not None:
        brief["price"] = float(min_price)
    if popularity is not None:
        brief["attendees"] = int(popularity)
    if rating is not None:
        brief["rating"] = round(float(rating), 2)
    return brief


def _history_brief(events: list[Event]) -> list[dict]:
    """Summarise a user's attended events as taste signals for the prompt."""
    return [
        {"title": e.title, "city": e.city, "tags": (e.tags or [])[:6]} for e in events
    ]


def _fallback(recs: list[RecommendedEvent]) -> list[AiRecommendedEvent]:
    """Wrap heuristic recommendations as AI results (no reason attached)."""
    return [AiRecommendedEvent(event=r.event, reason=None, score=r.score) for r in recs]


def _order_by_ai(
    ai_items: list[Any], candidates_by_id: dict[str, Row], limit: int
) -> list[AiRecommendedEvent]:
    """Map Gemini's ranked ids back onto candidate events, preserving order."""
    results: list[AiRecommendedEvent] = []
    seen: set[str] = set()
    for item in ai_items:
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("event_id") or item.get("id") or "").strip()
        if event_id not in candidates_by_id or event_id in seen:
            continue
        seen.add(event_id)
        reason = item.get("reason")
        row = candidates_by_id[event_id]
        results.append(
            AiRecommendedEvent(
                event=row.Event,
                reason=str(reason).strip() if reason else None,
            )
        )
        if len(results) >= limit:
            break
    return results


async def _cached(key: str) -> list[AiRecommendedEvent] | None:
    """Return cached AI recommendations for ``key`` if present."""
    cached = await cache.get_json(key)
    if cached is None:
        return None
    return [AiRecommendedEvent.model_validate(item) for item in cached]


async def _store(key: str, recs: list[AiRecommendedEvent]) -> None:
    """Cache AI recommendations under ``key`` for the recommendations TTL."""
    await cache.set_json(
        key, [r.model_dump(mode="json") for r in recs], cache.TTL_RECOMMENDATIONS
    )


def _personalized_prompt(
    history: list[dict], candidates: list[dict], limit: int
) -> str:
    """Build the Gemini prompt for a personalized recommendation request."""
    return (
        "You are an event recommendation engine for EventPulse, an event "
        "ticketing platform. Given a user's recent booking history and a list of "
        "upcoming candidate events, pick the events this user is most likely to "
        "enjoy.\n\n"
        f"User's recent bookings:\n{json.dumps(history)}\n\n"
        f"Candidate events:\n{json.dumps(candidates)}\n\n"
        f"Select up to {limit} candidate events, best match first. Respond with "
        'ONLY a JSON array of objects, each with keys "event_id" (must be one of '
        'the candidate ids) and "reason" (a short, friendly one-sentence '
        "explanation of why it fits this user). No markdown, no extra text."
    )


def _similar_prompt(source: dict, candidates: list[dict], limit: int) -> str:
    """Build the Gemini prompt for a similar-events request."""
    return (
        "You are an event recommendation engine for EventPulse. Given a source "
        "event and a list of candidate events, pick the candidates most similar "
        "to the source (by theme, category, tags, location, and audience).\n\n"
        f"Source event:\n{json.dumps(source)}\n\n"
        f"Candidate events:\n{json.dumps(candidates)}\n\n"
        f"Select up to {limit} candidate events, most similar first. Respond with "
        'ONLY a JSON array of objects, each with keys "event_id" (one of the '
        'candidate ids) and "reason" (a short one-sentence explanation of the '
        "similarity). No markdown, no extra text."
    )


async def _try_ai(
    gemini: GeminiClient,
    prompt: str,
    candidates_by_id: dict[str, Row],
    limit: int,
) -> list[AiRecommendedEvent] | None:
    """Run one Gemini ranking attempt; return ``None`` on any failure.

    Failures (GeminiError, non-list output, or no candidate ids matched) return
    ``None`` so the caller can fall back to the heuristic ranker.
    """
    try:
        ai_items = await gemini.generate_json(prompt)
    except GeminiError:
        return None
    if not isinstance(ai_items, list):
        return None
    return _order_by_ai(ai_items, candidates_by_id, limit) or None


async def get_ai_personalized(
    db: AsyncSession, user: User, limit: int = 10
) -> list[AiRecommendedEvent]:
    """Return Gemini-curated recommendations for a user.

    Genuine AI results are cached per user; heuristic fallbacks are not cached
    here (they carry their own cache under the heuristic key), so a transient
    Gemini failure never pins a degraded result for the full TTL.
    """
    key = f"{_AI_USER_PREFIX}{user.id}:{limit}"
    cached = await _cached(key)
    if cached is not None:
        return cached

    gemini = get_gemini()
    attended = await crud.user_attended_event_ids(db, user.id)
    candidates = await crud.candidate_events(
        db, datetime.now(UTC), attended, _AI_CANDIDATE_POOL
    )

    if candidates and gemini.is_configured:
        history_events = await crud.user_attended_event_briefs(
            db, user.id, _HISTORY_LIMIT
        )
        candidates_by_id = {str(row.Event.id): row for row in candidates}
        prompt = _personalized_prompt(
            _history_brief(history_events),
            [
                _event_brief(r.Event, r.min_price, r.popularity, r.avg_rating)
                for r in candidates
            ],
            limit,
        )
        result = await _try_ai(gemini, prompt, candidates_by_id, limit)
        if result:
            await _store(key, result)
            return result

    recs = await services.get_personalized_recommendations(db, user, limit)
    return _fallback(recs)


async def get_ai_similar(
    db: AsyncSession, event_id: uuid.UUID, limit: int = 10
) -> list[AiRecommendedEvent]:
    """Return Gemini-curated events similar to ``event_id`` (public).

    Genuine AI results are cached per event; heuristic fallbacks are not cached
    here, so a transient Gemini failure never pins a degraded result.
    """
    source = await events_services.get_event(db, event_id)  # 404 if missing

    key = f"{_AI_SIMILAR_PREFIX}{event_id}:{limit}"
    cached = await _cached(key)
    if cached is not None:
        return cached

    gemini = get_gemini()
    candidates = await crud.candidate_events(
        db, datetime.now(UTC), {event_id}, _AI_CANDIDATE_POOL
    )

    if candidates and gemini.is_configured:
        candidates_by_id = {str(row.Event.id): row for row in candidates}
        prompt = _similar_prompt(
            _event_brief(source),
            [
                _event_brief(r.Event, r.min_price, r.popularity, r.avg_rating)
                for r in candidates
            ],
            limit,
        )
        result = await _try_ai(gemini, prompt, candidates_by_id, limit)
        if result:
            await _store(key, result)
            return result

    recs = await services.get_similar_events(db, event_id, limit)
    return _fallback(recs)
