"""Tests for AI-powered recommendations (Gemini) with mocked model responses.

Covers the /recommendations/for-me and /events/{id}/similar endpoints, the AI
ranking path, graceful fallback to the heuristic ranker, auth/validation, and
the JSON-extraction helper.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.gemini import GeminiClient, GeminiError, _extract_json
from app.features.recommendations import ai
from tests.features.test_recommendations import (
    _make_category,
    _make_org,
    _published_event,
)

FOR_ME_URL = "/api/v1/recommendations/for-me"
EVENTS_URL = "/api/v1/events"


class _FakeGemini:
    """Stand-in for the Gemini client used to drive AI branches in tests."""

    def __init__(self, *, configured: bool = True, response=None, error: bool = False):
        self.is_configured = configured
        self._response = response
        self._error = error

    async def generate_json(self, prompt: str, *, temperature: float = 0.3):
        """Return the canned response or raise, mirroring the real client."""
        if self._error:
            raise GeminiError("simulated Gemini failure")
        return self._response


# --------------------------------------------------------------------------- #
# _extract_json helper
# --------------------------------------------------------------------------- #


def test_extract_json_plain() -> None:
    """Plain JSON is parsed as-is."""
    assert _extract_json('[{"event_id": "x"}]') == [{"event_id": "x"}]


def test_extract_json_strips_code_fence() -> None:
    """A ```json fenced response is unwrapped before parsing."""
    raw = '```json\n[{"event_id": "x", "reason": "y"}]\n```'
    assert _extract_json(raw) == [{"event_id": "x", "reason": "y"}]


def test_extract_json_finds_embedded_array() -> None:
    """A JSON array embedded in prose is recovered."""
    raw = 'Here you go: [{"event_id": "x"}] hope that helps'
    assert _extract_json(raw) == [{"event_id": "x"}]


def test_extract_json_raises_on_garbage() -> None:
    """Unparseable output raises GeminiError."""
    with pytest.raises(GeminiError):
        _extract_json("not json at all")


# --------------------------------------------------------------------------- #
# GeminiClient error normalization (no network / SDK required)
# --------------------------------------------------------------------------- #


async def test_client_unconfigured_raises_gemini_error() -> None:
    """An empty API key surfaces as GeminiError through the async wrapper."""
    client = GeminiClient(api_key="", model="gemini-2.0-flash")
    assert client.is_configured is False
    with pytest.raises(GeminiError):
        await client.generate_text("hello")


async def test_client_normalizes_model_construction_errors(monkeypatch) -> None:
    """A raw error while building the model is normalized to GeminiError."""
    client = GeminiClient(api_key="fake-key", model="gemini-2.0-flash")

    def _boom() -> None:
        raise RuntimeError("SDK construction blew up")

    monkeypatch.setattr(client, "_ensure_model", _boom)
    with pytest.raises(GeminiError):
        await client.generate_text("hello")


# --------------------------------------------------------------------------- #
# /recommendations/for-me
# --------------------------------------------------------------------------- #


async def test_for_me_uses_ai_ranking(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """When Gemini is configured, results follow the model's order with reasons."""
    admin = await make_user(email="ai-admin@example.com", role="admin")
    organizer = await make_user(email="ai-org@example.com")
    buyer = await make_user(email="ai-buyer@example.com")
    cat = await _make_category(client, admin, auth_headers, "AI Music")
    org_id = await _make_org(client, organizer, auth_headers, "AI Org")

    first_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat, city="Pune"
    )
    second_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat, city="Delhi"
    )

    # Gemini ranks the second event first and gives reasons.
    fake = _FakeGemini(
        response=[
            {"event_id": second_id, "reason": "Matches your taste for tech talks"},
            {"event_id": first_id, "reason": "Popular near you"},
        ]
    )
    monkeypatch.setattr(ai, "get_gemini", lambda: fake)

    resp = await client.get(FOR_ME_URL, headers=auth_headers(buyer))
    assert resp.status_code == 200
    body = resp.json()
    ids = [r["event"]["id"] for r in body]
    assert ids == [second_id, first_id]
    assert body[0]["reason"] == "Matches your taste for tech talks"


async def test_for_me_skips_unknown_ai_ids(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """Ids the model invents that aren't real candidates are ignored."""
    admin = await make_user(email="ai-admin2@example.com", role="admin")
    organizer = await make_user(email="ai-org2@example.com")
    buyer = await make_user(email="ai-buyer2@example.com")
    cat = await _make_category(client, admin, auth_headers, "AI Arts")
    org_id = await _make_org(client, organizer, auth_headers, "AI Org2")
    real_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat, city="Pune"
    )

    fake = _FakeGemini(
        response=[
            {"event_id": str(uuid.uuid4()), "reason": "hallucinated"},
            {"event_id": real_id, "reason": "real pick"},
        ]
    )
    monkeypatch.setattr(ai, "get_gemini", lambda: fake)

    resp = await client.get(FOR_ME_URL, headers=auth_headers(buyer))
    assert resp.status_code == 200
    body = resp.json()
    assert [r["event"]["id"] for r in body] == [real_id]


async def test_for_me_falls_back_when_unconfigured(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """With no API key, results come from the heuristic ranker (reason=None)."""
    admin = await make_user(email="ai-admin3@example.com", role="admin")
    organizer = await make_user(email="ai-org3@example.com")
    buyer = await make_user(email="ai-buyer3@example.com")
    cat = await _make_category(client, admin, auth_headers, "AI Jazz")
    org_id = await _make_org(client, organizer, auth_headers, "AI Org3")
    event_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat, city="Pune"
    )

    monkeypatch.setattr(ai, "get_gemini", lambda: _FakeGemini(configured=False))

    resp = await client.get(FOR_ME_URL, headers=auth_headers(buyer))
    assert resp.status_code == 200
    body = resp.json()
    assert event_id in [r["event"]["id"] for r in body]
    assert all(r["reason"] is None for r in body)


async def test_for_me_falls_back_on_gemini_error(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """A Gemini failure degrades to heuristic results rather than erroring."""
    admin = await make_user(email="ai-admin4@example.com", role="admin")
    organizer = await make_user(email="ai-org4@example.com")
    buyer = await make_user(email="ai-buyer4@example.com")
    cat = await _make_category(client, admin, auth_headers, "AI Rock")
    org_id = await _make_org(client, organizer, auth_headers, "AI Org4")
    event_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat, city="Pune"
    )

    monkeypatch.setattr(ai, "get_gemini", lambda: _FakeGemini(error=True))

    resp = await client.get(FOR_ME_URL, headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert event_id in [r["event"]["id"] for r in resp.json()]


async def test_for_me_requires_auth(client: AsyncClient) -> None:
    """The personalized AI feed requires authentication."""
    resp = await client.get(FOR_ME_URL)
    assert resp.status_code == 401


async def test_for_me_limit_validation(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An out-of-range limit is rejected with 422."""
    resp = await client.get(
        f"{FOR_ME_URL}?limit=0", headers=auth_headers(verified_user)
    )
    assert resp.status_code == 422
    resp = await client.get(
        f"{FOR_ME_URL}?limit=11", headers=auth_headers(verified_user)
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# /events/{id}/similar
# --------------------------------------------------------------------------- #


async def test_similar_uses_ai_ranking(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """Similar events follow the model's order and are public."""
    admin = await make_user(email="sim-admin@example.com", role="admin")
    organizer = await make_user(email="sim-org@example.com")
    cat = await _make_category(client, admin, auth_headers, "Sim Music")
    org_id = await _make_org(client, organizer, auth_headers, "Sim Org")
    source_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat, city="Pune"
    )
    a_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat, city="Pune"
    )
    b_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat, city="Delhi"
    )

    fake = _FakeGemini(
        response=[
            {"event_id": b_id, "reason": "Same genre"},
            {"event_id": a_id, "reason": "Same city and category"},
        ]
    )
    monkeypatch.setattr(ai, "get_gemini", lambda: fake)

    resp = await client.get(f"{EVENTS_URL}/{source_id}/similar")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["event"]["id"] for r in body] == [b_id, a_id]
    assert source_id not in [r["event"]["id"] for r in body]
    assert body[0]["reason"] == "Same genre"


async def test_similar_not_found(client: AsyncClient) -> None:
    """A similar-events request for a missing event returns 404."""
    resp = await client.get(f"{EVENTS_URL}/{uuid.uuid4()}/similar")
    assert resp.status_code == 404


async def test_similar_falls_back_on_error(
    client: AsyncClient, make_user, auth_headers, monkeypatch
) -> None:
    """A Gemini failure degrades similar events to the heuristic ranker."""
    admin = await make_user(email="sim-admin2@example.com", role="admin")
    organizer = await make_user(email="sim-org2@example.com")
    cat = await _make_category(client, admin, auth_headers, "Sim Tech")
    org_id = await _make_org(client, organizer, auth_headers, "Sim Org2")
    source_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat, city="Pune"
    )
    other_id, _ = await _published_event(
        client, organizer, auth_headers, org_id, category_id=cat, city="Pune"
    )

    monkeypatch.setattr(ai, "get_gemini", lambda: _FakeGemini(error=True))

    resp = await client.get(f"{EVENTS_URL}/{source_id}/similar")
    assert resp.status_code == 200
    assert other_id in [r["event"]["id"] for r in resp.json()]


async def test_similar_limit_validation(client: AsyncClient) -> None:
    """An out-of-range similar limit is rejected with 422."""
    resp = await client.get(f"{EVENTS_URL}/{uuid.uuid4()}/similar?limit=99")
    assert resp.status_code == 422
