"""Tests for the event AI chatbot (POST /events/{id}/chat)."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gemini import GeminiError
from app.features.chat import ai as chat_ai

EVENTS_URL = "/api/v1/events"
ORGS_URL = "/api/v1/organizations"

START = "2030-06-01T10:00:00Z"
END = "2030-06-01T18:00:00Z"


class _FakeGemini:
    """Stand-in for the Gemini client to drive the AI/fallback branches."""

    def __init__(self, *, configured: bool = True, text: str = "", error: bool = False):
        self.is_configured = configured
        self._text = text
        self._error = error

    async def generate_text(self, prompt: str, *, temperature: float = 0.7) -> str:
        """Return canned text or raise, mirroring the real client."""
        if self._error:
            raise GeminiError("simulated failure")
        return self._text


async def _create_event(
    client: AsyncClient, auth_headers, organizer, *, publish: bool = True
) -> str:
    """Create an org + event (with one ticket tier) and return the event id.

    Publishes the event by default, since the chatbot only answers about
    published events.
    """
    org = (
        await client.post(
            ORGS_URL,
            headers=auth_headers(organizer),
            json={"name": "Chat Org", "contact_email": "c@example.com"},
        )
    ).json()
    event = (
        await client.post(
            EVENTS_URL,
            headers=auth_headers(organizer),
            json={
                "organization_id": org["id"],
                "title": "Jazz Night",
                "description": "An evening of live jazz.",
                "venue_name": "Blue Room",
                "start_datetime": START,
                "end_datetime": END,
            },
        )
    ).json()
    await client.post(
        f"{EVENTS_URL}/{event['id']}/ticket-types",
        headers=auth_headers(organizer),
        json={"name": "GA", "price": "25.00", "quantity_total": 100},
    )
    if publish:
        await client.post(
            f"{EVENTS_URL}/{event['id']}/publish", headers=auth_headers(organizer)
        )
    return event["id"]


async def test_chat_uses_gemini_when_configured(
    client: AsyncClient, make_user, verified_user, auth_headers, monkeypatch
) -> None:
    """A configured Gemini answers the question and decrements the quota."""
    organizer = await make_user(email="chatorg1@example.com")
    event_id = await _create_event(client, auth_headers, organizer)
    monkeypatch.setattr(
        chat_ai, "get_gemini", lambda: _FakeGemini(text="Doors open at 10am.")
    )

    resp = await client.post(
        f"{EVENTS_URL}/{event_id}/chat",
        headers=auth_headers(verified_user),
        json={"question": "When do doors open?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Doors open at 10am."
    assert body["generated_by_ai"] is True
    assert body["questions_remaining"] == 4


async def test_chat_falls_back_when_unconfigured(
    client: AsyncClient, make_user, verified_user, auth_headers, monkeypatch
) -> None:
    """Without a Gemini key, a polite fallback answer is returned (still 200)."""
    organizer = await make_user(email="chatorg2@example.com")
    event_id = await _create_event(client, auth_headers, organizer)
    monkeypatch.setattr(chat_ai, "get_gemini", lambda: _FakeGemini(configured=False))

    resp = await client.post(
        f"{EVENTS_URL}/{event_id}/chat",
        headers=auth_headers(verified_user),
        json={"question": "Where is it?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["generated_by_ai"] is False
    assert "unavailable" in body["answer"].lower()


async def test_chat_falls_back_on_gemini_error(
    client: AsyncClient, make_user, verified_user, auth_headers, monkeypatch
) -> None:
    """A Gemini failure degrades to the fallback answer."""
    organizer = await make_user(email="chatorg3@example.com")
    event_id = await _create_event(client, auth_headers, organizer)
    monkeypatch.setattr(chat_ai, "get_gemini", lambda: _FakeGemini(error=True))

    resp = await client.post(
        f"{EVENTS_URL}/{event_id}/chat",
        headers=auth_headers(verified_user),
        json={"question": "Anything?"},
    )
    assert resp.status_code == 200
    assert resp.json()["generated_by_ai"] is False


async def test_chat_rate_limited_after_five_per_hour(
    client: AsyncClient, make_user, verified_user, auth_headers, monkeypatch
) -> None:
    """A user gets 5 answers per event per hour, then 429; quota counts down."""
    organizer = await make_user(email="chatorg4@example.com")
    event_id = await _create_event(client, auth_headers, organizer)
    monkeypatch.setattr(chat_ai, "get_gemini", lambda: _FakeGemini(text="Yes."))

    remaining = []
    for _ in range(5):
        resp = await client.post(
            f"{EVENTS_URL}/{event_id}/chat",
            headers=auth_headers(verified_user),
            json={"question": "Is parking available?"},
        )
        assert resp.status_code == 200
        remaining.append(resp.json()["questions_remaining"])
    assert remaining == [4, 3, 2, 1, 0]

    sixth = await client.post(
        f"{EVENTS_URL}/{event_id}/chat",
        headers=auth_headers(verified_user),
        json={"question": "One more?"},
    )
    assert sixth.status_code == 429
    assert "hour" in sixth.json()["message"].lower()


async def test_chat_rate_limit_is_per_event(
    client: AsyncClient, make_user, verified_user, auth_headers, monkeypatch
) -> None:
    """Exhausting the quota on one event does not block questions on another."""
    organizer = await make_user(email="chatorg5@example.com")
    event_a = await _create_event(client, auth_headers, organizer)
    event_b = await _create_event(client, auth_headers, organizer)
    monkeypatch.setattr(chat_ai, "get_gemini", lambda: _FakeGemini(text="Yes."))

    for _ in range(5):
        await client.post(
            f"{EVENTS_URL}/{event_a}/chat",
            headers=auth_headers(verified_user),
            json={"question": "q"},
        )
    blocked = await client.post(
        f"{EVENTS_URL}/{event_a}/chat",
        headers=auth_headers(verified_user),
        json={"question": "q"},
    )
    assert blocked.status_code == 429

    other = await client.post(
        f"{EVENTS_URL}/{event_b}/chat",
        headers=auth_headers(verified_user),
        json={"question": "q"},
    )
    assert other.status_code == 200
    assert other.json()["questions_remaining"] == 4


async def test_chat_unknown_event_404(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Chatting about a nonexistent event returns 404."""
    resp = await client.post(
        f"{EVENTS_URL}/{uuid.uuid4()}/chat",
        headers=auth_headers(verified_user),
        json={"question": "Hello?"},
    )
    assert resp.status_code == 404


async def test_chat_unpublished_event_404(
    client: AsyncClient, make_user, verified_user, auth_headers
) -> None:
    """A draft (unpublished) event is not answerable — returns 404, no leak."""
    organizer = await make_user(email="chatorg8@example.com")
    event_id = await _create_event(client, auth_headers, organizer, publish=False)

    resp = await client.post(
        f"{EVENTS_URL}/{event_id}/chat",
        headers=auth_headers(verified_user),
        json={"question": "What's this event about?"},
    )
    assert resp.status_code == 404


async def test_chat_404_does_not_consume_quota(
    client: AsyncClient, make_user, verified_user, auth_headers, monkeypatch
) -> None:
    """A 404 (missing event) must not spend the caller's hourly quota."""
    from app.core.redis import get_redis

    resp = await client.post(
        f"{EVENTS_URL}/{uuid.uuid4()}/chat",
        headers=auth_headers(verified_user),
        json={"question": "Hello?"},
    )
    assert resp.status_code == 404
    # No chat counter key should have been created for this user.
    keys = await get_redis().keys(f"chat:questions:{verified_user.id}:*")
    assert keys == []


async def test_chat_requires_auth(client: AsyncClient) -> None:
    """The chatbot endpoint requires authentication."""
    resp = await client.post(
        f"{EVENTS_URL}/{uuid.uuid4()}/chat", json={"question": "Hello?"}
    )
    assert resp.status_code == 401


async def test_chat_blank_question_422(
    client: AsyncClient,
    make_user,
    verified_user,
    auth_headers,
    db_session: AsyncSession,
) -> None:
    """A blank/whitespace question is rejected with 422 before any quota is spent."""
    organizer = await make_user(email="chatorg6@example.com")
    event_id = await _create_event(client, auth_headers, organizer)

    resp = await client.post(
        f"{EVENTS_URL}/{event_id}/chat",
        headers=auth_headers(verified_user),
        json={"question": "   "},
    )
    assert resp.status_code == 422


async def test_chat_question_too_long_422(
    client: AsyncClient, make_user, verified_user, auth_headers
) -> None:
    """An over-length question is rejected with 422."""
    organizer = await make_user(email="chatorg7@example.com")
    event_id = await _create_event(client, auth_headers, organizer)

    resp = await client.post(
        f"{EVENTS_URL}/{event_id}/chat",
        headers=auth_headers(verified_user),
        json={"question": "x" * 1001},
    )
    assert resp.status_code == 422
