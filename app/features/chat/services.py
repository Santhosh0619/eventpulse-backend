"""Business logic for the event AI chatbot, including per-user rate limiting."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, TooManyRequestsError
from app.core.redis import record_chat_question
from app.features.chat import ai
from app.features.chat.schemas import ChatResponse
from app.features.events import services as events_services
from app.features.tickets import services as tickets_services
from app.features.users.models import User
from app.shared.enums import EventStatus


async def answer_question(
    db: AsyncSession, event_id: uuid.UUID, user: User, question: str
) -> ChatResponse:
    """Answer an attendee's question about an event (rate-limited per user+event).

    Only published events are answerable, so unpublished (draft/cancelled) events
    and their inactive-tier pricing are never disclosed through the chatbot.

    Raises:
        NotFoundError: If the event does not exist or is not published (before any
            quota is spent).
        TooManyRequestsError: If the user exceeds the hourly question quota.
    """
    event = await events_services.get_event(db, event_id)  # 404 if missing
    if event.status != EventStatus.PUBLISHED.value:
        raise NotFoundError("Event not found")

    limit = settings.CHATBOT_MAX_QUESTIONS_PER_HOUR
    count = await record_chat_question(
        str(user.id), str(event_id), settings.CHATBOT_WINDOW_SECONDS
    )
    if count > limit:
        raise TooManyRequestsError(
            f"You can ask up to {limit} questions per event per hour. "
            "Please try again later."
        )

    # Only expose active (on-sale/announced) tiers to the model.
    tiers = [t for t in await tickets_services.list_tiers(db, event_id) if t.is_active]
    answer, generated_by_ai = await ai.answer_question(event, tiers, question)
    return ChatResponse(
        answer=answer,
        generated_by_ai=generated_by_ai,
        questions_remaining=max(0, limit - count),
    )
