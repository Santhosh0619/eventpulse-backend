"""AI content moderation for reviews using Google Gemini.

Classifies review text into one of three actions before it is persisted:

- ``allow``  — publish normally
- ``flag``   — save but hide until an organizer approves it
- ``reject`` — refuse (spam / abusive / inappropriate)

Moderation fails **open**: if Gemini is unconfigured, errors, or returns an
unrecognized label, the review is allowed. This keeps genuine reviews flowing
when the AI is unavailable rather than silently blocking users; abusive content
can still be hidden later by an organizer or admin.
"""

from app.core.gemini import GeminiError, get_gemini

ALLOW = "allow"
FLAG = "flag"
REJECT = "reject"

_VALID = {ALLOW, FLAG, REJECT}


async def moderate_review(title: str | None, comment: str | None) -> str:
    """Return an ``allow`` / ``flag`` / ``reject`` decision for review text."""
    text = "\n".join(part for part in (title, comment) if part).strip()
    if not text:
        # Nothing to moderate (rating-only review).
        return ALLOW

    gemini = get_gemini()
    if not gemini.is_configured:
        return ALLOW

    prompt = (
        "You are a content moderator for event reviews on a ticketing platform. "
        "Classify the following review text into exactly one label:\n"
        '- "allow": normal, acceptable feedback (even if negative or critical).\n'
        '- "flag": borderline — mild profanity, possible spam, or needs a human '
        "look.\n"
        '- "reject": clearly inappropriate — hate speech, harassment, threats, '
        "explicit content, or obvious spam/scam.\n\n"
        f"Review text:\n{text}\n\n"
        "Respond with ONLY the single word: allow, flag, or reject."
    )
    try:
        raw = await gemini.generate_text(prompt, temperature=0.0)
    except GeminiError:
        return ALLOW

    decision = raw.strip().lower().strip(".\"' ")
    # Extract the first valid token in case the model adds stray words.
    for token in decision.replace("\n", " ").split():
        cleaned = token.strip(".\"' ")
        if cleaned in _VALID:
            return cleaned
    return ALLOW
