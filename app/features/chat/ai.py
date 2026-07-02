"""Gemini-backed answering for the event chatbot.

Builds a compact context from an event's public details and ticket tiers, then
asks Gemini to answer the attendee's question grounded in that context. Degrades
gracefully: when Gemini is unconfigured or errors, a polite fallback message is
returned instead so the endpoint never fails hard.
"""

from app.core.gemini import GeminiError, get_gemini
from app.features.events.models import Event
from app.features.tickets.models import TicketType

_FALLBACK_ANSWER = (
    "Sorry, the AI assistant is unavailable right now. Please check the event "
    "details on this page or contact the organizer for help."
)


def _event_context(event: Event, tiers: list[TicketType]) -> str:
    """Return a plain-text context block describing the event for the model."""
    lines = [f"Title: {event.title}"]
    if event.short_description:
        lines.append(f"Summary: {event.short_description}")
    if event.description:
        lines.append(f"Description: {event.description[:1500]}")
    lines.append(f"Starts: {event.start_datetime.isoformat()}")
    lines.append(f"Ends: {event.end_datetime.isoformat()}")
    location = ", ".join(
        part
        for part in (event.venue_name, event.venue_address, event.city, event.country)
        if part
    )
    if location:
        lines.append(f"Location: {location}")
    if event.max_capacity:
        lines.append(f"Capacity: {event.max_capacity}")
    if event.tags:
        lines.append(f"Tags: {', '.join(str(t) for t in event.tags)}")
    if tiers:
        tier_text = "; ".join(f"{t.name} ({t.currency} {t.price})" for t in tiers)
        lines.append(f"Ticket tiers: {tier_text}")
    return "\n".join(lines)


def _prompt(context: str, question: str) -> str:
    """Build the Gemini prompt for one attendee question."""
    return (
        "You are a helpful assistant answering attendee questions about a specific "
        "event on EventPulse, an event ticketing platform. Answer ONLY using the "
        "event details below. If the answer is not in the details, say you don't "
        "have that information and suggest contacting the organizer. Keep the answer "
        "friendly and concise (1-3 sentences), and respond in plain text.\n\n"
        f"Event details:\n{context}\n\n"
        f"Attendee question: {question}"
    )


async def answer_question(
    event: Event, tiers: list[TicketType], question: str
) -> tuple[str, bool]:
    """Return ``(answer, generated_by_ai)`` for a question about an event.

    Uses Gemini when configured and reachable; otherwise returns a fallback
    message with ``generated_by_ai=False``.
    """
    gemini = get_gemini()
    if gemini.is_configured:
        prompt = _prompt(_event_context(event, tiers), question)
        try:
            answer = await gemini.generate_text(prompt, temperature=0.5)
        except GeminiError:
            answer = ""
        if answer.strip():
            return answer.strip(), True
    return _FALLBACK_ANSWER, False
