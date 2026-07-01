"""Google Gemini API client wrapper for EventPulse AI features.

A thin, async-friendly wrapper around the ``google-generativeai`` SDK shared by
every AI feature (recommendations, description generation, review moderation,
analytics summaries, and the attendee chatbot).

The SDK is synchronous, so blocking calls run in a worker thread to avoid
stalling the event loop. Callers should catch :class:`GeminiError` and fall back
to non-AI behaviour so the platform keeps working when Gemini is unconfigured,
rate-limited, or unreachable.
"""

import asyncio
import json
import re
from typing import Any

from app.core.config import settings

# Matches a leading/trailing Markdown code fence (```json ... ```), which Gemini
# frequently wraps JSON responses in despite instructions not to.
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class GeminiError(Exception):
    """Raised when a Gemini request fails or returns an unusable response."""


def _extract_json(raw: str) -> Any:
    """Parse a JSON value from a raw model response, tolerating code fences."""
    text = raw.strip()
    # Strip a wrapping ```json ... ``` fence if present.
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # Fall back to extracting the first JSON array/object substring.
        match = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        raise GeminiError(f"Gemini did not return valid JSON: {exc}") from exc


class GeminiClient:
    """Lazily-configured client around a single Gemini generative model."""

    def __init__(self, api_key: str, model: str) -> None:
        """Store credentials; the underlying SDK model is built on first use."""
        self._api_key = api_key.strip()
        self._model_name = model
        self._model: Any = None

    @property
    def is_configured(self) -> bool:
        """Return whether an API key is available for requests."""
        return bool(self._api_key)

    def _ensure_model(self) -> Any:
        """Build (and cache) the SDK model, raising ``GeminiError`` on failure."""
        if self._model is not None:
            return self._model
        if not self._api_key:
            raise GeminiError("GEMINI_API_KEY is not configured")
        try:
            import google.generativeai as genai
        except ImportError as exc:  # pragma: no cover - import guard
            raise GeminiError("google-generativeai is not installed") from exc
        genai.configure(api_key=self._api_key)
        self._model = genai.GenerativeModel(self._model_name)
        return self._model

    def _generate_sync(self, prompt: str, temperature: float) -> str:
        """Run a blocking ``generate_content`` call and return its text.

        Model construction (``configure`` / ``GenerativeModel``) and the request
        itself both run inside the guard so any SDK error — including one raised
        while building the model from a malformed key — is normalised to
        :class:`GeminiError`, preserving the "always degrade gracefully" contract.
        """
        try:
            model = self._ensure_model()
            response = model.generate_content(
                prompt,
                generation_config={"temperature": temperature},
            )
        except GeminiError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise any SDK error
            raise GeminiError(f"Gemini request failed: {exc}") from exc
        text = getattr(response, "text", None)
        if not text or not text.strip():
            raise GeminiError("Gemini returned an empty response")
        return text

    async def generate_text(self, prompt: str, *, temperature: float = 0.7) -> str:
        """Generate free-form text for ``prompt`` (runs off the event loop)."""
        return await asyncio.to_thread(self._generate_sync, prompt, temperature)

    async def generate_json(self, prompt: str, *, temperature: float = 0.3) -> Any:
        """Generate a response and parse it as JSON, raising on malformed output."""
        raw = await self.generate_text(prompt, temperature=temperature)
        return _extract_json(raw)


# Module-level singleton used by feature services. Rebuilt only on process start,
# so config changes require a restart (consistent with the rest of settings).
gemini_client = GeminiClient(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)


def get_gemini() -> GeminiClient:
    """Return the shared Gemini client singleton."""
    return gemini_client
