"""Tests for AI-generated event descriptions (Gemini) with mocked responses."""

from httpx import AsyncClient

from app.core.gemini import GeminiError
from app.features.events import services as events_services

URL = "/api/v1/events/generate-description"


class _FakeGemini:
    """Stand-in for the Gemini client to drive AI branches in tests."""

    def __init__(self, *, configured: bool = True, text: str = "", error: bool = False):
        self.is_configured = configured
        self._text = text
        self._error = error

    async def generate_text(self, prompt: str, *, temperature: float = 0.7) -> str:
        """Return canned text or raise, mirroring the real client."""
        if self._error:
            raise GeminiError("simulated failure")
        return self._text


async def test_generate_description_uses_ai(
    client: AsyncClient, verified_user, auth_headers, monkeypatch
) -> None:
    """A configured Gemini returns the model's text with ai_generated=True."""
    fake = _FakeGemini(text="  A vibrant evening of live jazz and fine wine.  ")
    monkeypatch.setattr(events_services, "get_gemini", lambda: fake)

    resp = await client.post(
        URL,
        headers=auth_headers(verified_user),
        json={"keywords": ["jazz", "wine"], "tone": "elegant"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ai_generated"] is True
    assert body["description"] == "A vibrant evening of live jazz and fine wine."


async def test_generate_description_fallback_when_unconfigured(
    client: AsyncClient, verified_user, auth_headers, monkeypatch
) -> None:
    """With no API key, a templated description is returned (ai_generated=False)."""
    monkeypatch.setattr(
        events_services, "get_gemini", lambda: _FakeGemini(configured=False)
    )

    resp = await client.post(
        URL,
        headers=auth_headers(verified_user),
        json={"keywords": ["hackathon", "networking"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ai_generated"] is False
    assert "hackathon" in body["description"]
    assert "networking" in body["description"]


async def test_generate_description_fallback_on_error(
    client: AsyncClient, verified_user, auth_headers, monkeypatch
) -> None:
    """A Gemini failure degrades to the templated description."""
    monkeypatch.setattr(events_services, "get_gemini", lambda: _FakeGemini(error=True))

    resp = await client.post(
        URL,
        headers=auth_headers(verified_user),
        json={"keywords": ["marathon"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ai_generated"] is False
    assert "marathon" in body["description"]


async def test_generate_description_requires_auth(client: AsyncClient) -> None:
    """The endpoint requires authentication."""
    resp = await client.post(URL, json={"keywords": ["x"]})
    assert resp.status_code == 401


async def test_generate_description_rejects_empty_keywords(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """An empty keyword list is rejected with 422."""
    resp = await client.post(
        URL, headers=auth_headers(verified_user), json={"keywords": []}
    )
    assert resp.status_code == 422


async def test_generate_description_rejects_all_whitespace_keywords(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """Keywords that are all whitespace are rejected with 422."""
    resp = await client.post(
        URL, headers=auth_headers(verified_user), json={"keywords": ["  ", ""]}
    )
    assert resp.status_code == 422


async def test_generate_description_rejects_too_many_keywords(
    client: AsyncClient, verified_user, auth_headers
) -> None:
    """More than ten keywords is rejected with 422."""
    resp = await client.post(
        URL,
        headers=auth_headers(verified_user),
        json={"keywords": [f"k{i}" for i in range(11)]},
    )
    assert resp.status_code == 422
