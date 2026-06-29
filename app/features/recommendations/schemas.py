"""Pydantic response schemas for recommendations."""

from pydantic import BaseModel

from app.features.events.schemas import EventRead


class RecommendedEvent(BaseModel):
    """An event paired with its recommendation relevance score (0.0-1.0)."""

    event: EventRead
    score: float
