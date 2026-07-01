"""Tests for AI review moderation (Gemini) with mocked moderation decisions."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gemini import GeminiError
from app.features.reviews import moderation
from tests.features.test_reviews import _attended_event

EVENTS_URL = "/api/v1/events"
REVIEWS_URL = "/api/v1/reviews"


class _FakeGemini:
    """Stand-in Gemini client returning a canned moderation decision."""

    def __init__(
        self, *, configured: bool = True, text: str = "allow", error: bool = False
    ):
        self.is_configured = configured
        self._text = text
        self._error = error

    async def generate_text(self, prompt: str, *, temperature: float = 0.0) -> str:
        """Return the canned decision text or raise, mirroring the real client."""
        if self._error:
            raise GeminiError("simulated failure")
        return self._text


def _set_decision(monkeypatch, **kwargs) -> None:
    """Patch the moderation module's Gemini client with a fake."""
    monkeypatch.setattr(moderation, "get_gemini", lambda: _FakeGemini(**kwargs))


async def _submit(client, buyer, auth_headers, event_id, comment="Great event!"):
    """Submit a review as the buyer and return the response."""
    return await client.post(
        f"{EVENTS_URL}/{event_id}/reviews",
        headers=auth_headers(buyer),
        json={"rating": 5, "title": "Nice", "comment": comment},
    )


async def test_allowed_review_is_visible(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession, monkeypatch
) -> None:
    """An 'allow' decision publishes the review normally."""
    organizer = await make_user(email="mod-org1@example.com")
    buyer = await make_user(email="mod-buyer1@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    _set_decision(monkeypatch, text="allow")

    resp = await _submit(client, buyer, auth_headers, event_id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_visible"] is True
    assert body["moderation_status"] == "approved"

    # Visible in the public list.
    public = await client.get(f"{EVENTS_URL}/{event_id}/reviews")
    assert len(public.json()) == 1


async def test_flagged_review_is_hidden(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession, monkeypatch
) -> None:
    """A 'flag' decision saves the review but hides it from the public list."""
    organizer = await make_user(email="mod-org2@example.com")
    buyer = await make_user(email="mod-buyer2@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    _set_decision(monkeypatch, text="flag")

    resp = await _submit(client, buyer, auth_headers, event_id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_visible"] is False
    assert body["moderation_status"] == "flagged"

    # Hidden from the public list...
    public = await client.get(f"{EVENTS_URL}/{event_id}/reviews")
    assert public.json() == []
    # ...but visible to the organizer's management view.
    mgmt = await client.get(
        f"{EVENTS_URL}/{event_id}/reviews/management",
        headers=auth_headers(organizer),
    )
    assert len(mgmt.json()) == 1
    assert mgmt.json()[0]["moderation_status"] == "flagged"


async def test_rejected_review_returns_422(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession, monkeypatch
) -> None:
    """A 'reject' decision refuses the review with 422."""
    organizer = await make_user(email="mod-org3@example.com")
    buyer = await make_user(email="mod-buyer3@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    _set_decision(monkeypatch, text="reject")

    resp = await _submit(client, buyer, auth_headers, event_id, comment="spam spam")
    assert resp.status_code == 422
    assert "inappropriate" in resp.text.lower()

    # Nothing was saved.
    public = await client.get(f"{EVENTS_URL}/{event_id}/reviews")
    assert public.json() == []


async def test_moderation_fails_open_when_unconfigured(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession, monkeypatch
) -> None:
    """With no API key the review is allowed (fail-open)."""
    organizer = await make_user(email="mod-org4@example.com")
    buyer = await make_user(email="mod-buyer4@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    _set_decision(monkeypatch, configured=False)

    resp = await _submit(client, buyer, auth_headers, event_id)
    assert resp.status_code == 201
    assert resp.json()["is_visible"] is True


async def test_moderation_fails_open_on_error(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession, monkeypatch
) -> None:
    """A Gemini error allows the review rather than blocking the user."""
    organizer = await make_user(email="mod-org5@example.com")
    buyer = await make_user(email="mod-buyer5@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    _set_decision(monkeypatch, error=True)

    resp = await _submit(client, buyer, auth_headers, event_id)
    assert resp.status_code == 201
    assert resp.json()["is_visible"] is True


async def test_organizer_can_approve_flagged_review(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession, monkeypatch
) -> None:
    """An org member can approve a flagged review, making it public."""
    organizer = await make_user(email="mod-org6@example.com")
    buyer = await make_user(email="mod-buyer6@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    _set_decision(monkeypatch, text="flag")
    review = (await _submit(client, buyer, auth_headers, event_id)).json()

    approve = await client.post(
        f"{REVIEWS_URL}/{review['id']}/approve",
        headers=auth_headers(organizer),
    )
    assert approve.status_code == 200
    assert approve.json()["is_visible"] is True
    assert approve.json()["moderation_status"] == "approved"

    public = await client.get(f"{EVENTS_URL}/{event_id}/reviews")
    assert len(public.json()) == 1


async def test_management_and_approve_require_org_member(
    client: AsyncClient, make_user, auth_headers, db_session: AsyncSession, monkeypatch
) -> None:
    """Non-members cannot view the management list or approve reviews."""
    organizer = await make_user(email="mod-org7@example.com")
    buyer = await make_user(email="mod-buyer7@example.com")
    outsider = await make_user(email="mod-outsider7@example.com")
    event_id = await _attended_event(client, organizer, buyer, auth_headers, db_session)
    _set_decision(monkeypatch, text="flag")
    review = (await _submit(client, buyer, auth_headers, event_id)).json()

    mgmt = await client.get(
        f"{EVENTS_URL}/{event_id}/reviews/management",
        headers=auth_headers(outsider),
    )
    assert mgmt.status_code == 403

    approve = await client.post(
        f"{REVIEWS_URL}/{review['id']}/approve",
        headers=auth_headers(outsider),
    )
    assert approve.status_code == 403


async def test_approve_missing_review_returns_404(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Approving a non-existent review returns 404."""
    resp = await client.post(
        f"{REVIEWS_URL}/{uuid.uuid4()}/approve",
        headers=auth_headers(verified_user),
    )
    assert resp.status_code == 404
