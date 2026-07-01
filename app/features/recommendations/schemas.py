"""Pydantic response schemas for recommendations."""

from pydantic import BaseModel

from app.features.events.schemas import EventRead


class RecommendedEvent(BaseModel):
    """An event paired with its recommendation relevance score (0.0-1.0)."""

    event: EventRead
    score: float


class AiRecommendedEvent(BaseModel):
    """An AI-recommended event with a short natural-language rationale.

    ``reason`` is populated when the Gemini model curated the pick and is
    ``None`` when the result came from the heuristic fallback. ``score`` carries
    the heuristic relevance score for fallback picks; AI-curated picks have no
    score (``None``) since the model, not the scorer, ordered them.
    """

    event: EventRead
    reason: str | None = None
    score: float | None = None
