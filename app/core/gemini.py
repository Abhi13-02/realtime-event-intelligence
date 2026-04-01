"""Gemini client for topic expansion on the API side."""

from __future__ import annotations

from functools import lru_cache

from google import genai

from app.config import get_settings

_MODEL = "gemini-2.5-flash"


class TopicExpansionError(Exception):
    """Raised when topic expansion via Gemini fails."""


class GeminiTopicExpander:
    """Small wrapper around Gemini for semantic topic expansion."""

    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    def expand_topic(self, name: str, description: str | None = None) -> str:
        prompt = f"""You expand user-created monitoring topics for semantic search.

Topic name: {name}
Topic description: {description or "None provided"}

Task:
- Write one concise paragraph that broadens the topic into relevant entities, terms, products, companies, events, synonyms, and adjacent concepts.
- Preserve the user's intent.
- Do not add formatting, bullet points, or labels.
- Return only the expanded description text."""

        try:
            response = self._client.models.generate_content(
                model=_MODEL,
                contents=prompt,
            )
            expanded_description = (response.text or "").strip()
        except Exception as exc:  # pragma: no cover - provider/network failures
            raise TopicExpansionError(f"Gemini API error: {exc}") from exc

        if not expanded_description:
            raise TopicExpansionError("Gemini returned an empty topic expansion.")

        return expanded_description


@lru_cache
def get_topic_expander() -> GeminiTopicExpander:
    """Return a cached Gemini client instance."""
    settings = get_settings()
    return GeminiTopicExpander(api_key=settings.gemini_api_key)
