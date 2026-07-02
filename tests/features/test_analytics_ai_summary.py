"""Tests for the AI analytics summary endpoint (GET /analytics/ai-summary)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gemini import GeminiError
from app.features.analytics import ai
from tests.features.test_analytics import _setup_confirmed_order

ANALYTICS_URL = "/api/v1/analytics"


class _FakeGemini:
    """Stand-in for the Gemini client to drive the AI/fallback branches."""

    def __init__(self, *, configured: bool = True, response="", error: bool = False):
        self.is_configured = configured
        self._response = response
        self._error = error

    async def generate_text(self, prompt: str, *, temperature: float = 0.7) -> str:
        """Return the canned text or raise, mirroring the real client."""
        if self._error:
            raise GeminiError("simulated Gemini failure")
        return self._response


async def test_ai_summary_uses_gemini_when_configured(
    client: AsyncClient,
    make_user,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """A configured Gemini client produces the AI-generated paragraph."""
    organizer = await make_user(email="aiorg1@example.com")
    buyer = await make_user(email="aibuyer1@example.com")
    _, event_id, _ = await _setup_confirmed_order(
        client, db_session, organizer, buyer, auth_headers, quantity=2
    )
    monkeypatch.setattr(
        ai, "get_gemini", lambda: _FakeGemini(response="Sales look strong.")
    )

    resp = await client.get(
        f"{ANALYTICS_URL}/ai-summary",
        params={"event_id": event_id},
        headers=auth_headers(organizer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["event_id"] == event_id
    assert body["generated_by_ai"] is True
    assert body["summary"] == "Sales look strong."


async def test_ai_summary_falls_back_when_unconfigured(
    client: AsyncClient,
    make_user,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """Without a Gemini key, a deterministic summary from the numbers is returned."""
    organizer = await make_user(email="aiorg2@example.com")
    buyer = await make_user(email="aibuyer2@example.com")
    _, event_id, _ = await _setup_confirmed_order(
        client, db_session, organizer, buyer, auth_headers, quantity=2, check_in=True
    )
    monkeypatch.setattr(ai, "get_gemini", lambda: _FakeGemini(configured=False))

    resp = await client.get(
        f"{ANALYTICS_URL}/ai-summary",
        params={"event_id": event_id},
        headers=auth_headers(organizer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["generated_by_ai"] is False
    # Deterministic template reflects the confirmed order and check-in.
    assert "2 tickets" in body["summary"]
    assert "1 order" in body["summary"]
    assert "checked in" in body["summary"]


async def test_ai_summary_falls_back_on_gemini_error(
    client: AsyncClient,
    make_user,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """A Gemini failure degrades to the deterministic template summary."""
    organizer = await make_user(email="aiorg3@example.com")
    buyer = await make_user(email="aibuyer3@example.com")
    _, event_id, _ = await _setup_confirmed_order(
        client, db_session, organizer, buyer, auth_headers, quantity=1
    )
    monkeypatch.setattr(ai, "get_gemini", lambda: _FakeGemini(error=True))

    resp = await client.get(
        f"{ANALYTICS_URL}/ai-summary",
        params={"event_id": event_id},
        headers=auth_headers(organizer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["generated_by_ai"] is False
    assert "1 ticket " in body["summary"]  # singular, no trailing 's'


async def test_ai_summary_no_sales_yet(
    client: AsyncClient,
    make_user,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
) -> None:
    """An event with no confirmed sales returns a graceful 'no sales yet' summary."""
    organizer = await make_user(email="aiorg4@example.com")

    org = (
        await client.post(
            "/api/v1/organizations",
            headers=auth_headers(organizer),
            json={"name": "Quiet Org", "contact_email": "q@example.com"},
        )
    ).json()
    event = (
        await client.post(
            "/api/v1/events",
            headers=auth_headers(organizer),
            json={
                "organization_id": org["id"],
                "title": "Quiet Event",
                "description": "d",
                "venue_name": "v",
                "start_datetime": "2030-06-01T10:00:00Z",
                "end_datetime": "2030-06-01T18:00:00Z",
            },
        )
    ).json()
    monkeypatch.setattr(ai, "get_gemini", lambda: _FakeGemini(configured=False))

    resp = await client.get(
        f"{ANALYTICS_URL}/ai-summary",
        params={"event_id": event["id"]},
        headers=auth_headers(organizer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["generated_by_ai"] is False
    assert "no confirmed sales yet" in body["summary"]


async def test_ai_summary_forbidden_for_non_member(
    client: AsyncClient,
    make_user,
    auth_headers,
    db_session: AsyncSession,
) -> None:
    """A non-member cannot read an event's AI summary."""
    organizer = await make_user(email="aiorg5@example.com")
    buyer = await make_user(email="aibuyer5@example.com")
    outsider = await make_user(email="aioutsider5@example.com")
    _, event_id, _ = await _setup_confirmed_order(
        client, db_session, organizer, buyer, auth_headers
    )
    resp = await client.get(
        f"{ANALYTICS_URL}/ai-summary",
        params={"event_id": event_id},
        headers=auth_headers(outsider),
    )
    assert resp.status_code == 403


async def test_ai_summary_requires_auth(client: AsyncClient) -> None:
    """The AI summary endpoint requires authentication."""
    resp = await client.get(
        f"{ANALYTICS_URL}/ai-summary", params={"event_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 401


async def test_ai_summary_unknown_event_404(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """The AI summary for an unknown event returns 404."""
    resp = await client.get(
        f"{ANALYTICS_URL}/ai-summary",
        params={"event_id": str(uuid.uuid4())},
        headers=auth_headers(verified_user),
    )
    assert resp.status_code == 404


@pytest.mark.parametrize("blank", ["", "   "])
async def test_ai_summary_blank_ai_response_falls_back(
    client: AsyncClient,
    make_user,
    auth_headers,
    db_session: AsyncSession,
    monkeypatch,
    blank: str,
) -> None:
    """A blank/whitespace AI response degrades to the deterministic summary."""
    organizer = await make_user(email=f"aiorg6{len(blank)}@example.com")
    buyer = await make_user(email=f"aibuyer6{len(blank)}@example.com")
    _, event_id, _ = await _setup_confirmed_order(
        client, db_session, organizer, buyer, auth_headers, quantity=2
    )
    monkeypatch.setattr(ai, "get_gemini", lambda: _FakeGemini(response=blank))

    resp = await client.get(
        f"{ANALYTICS_URL}/ai-summary",
        params={"event_id": event_id},
        headers=auth_headers(organizer),
    )
    assert resp.status_code == 200
    assert resp.json()["generated_by_ai"] is False
