"""Gemini client for topic expansion on the API side."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from google import genai

from app.config import get_settings

_MODEL = "gemini-2.5-flash-lite"


class TopicExpansionError(Exception):
    """Raised when topic expansion via Gemini fails."""


@dataclass
class TopicExpansionResult:
    """Structured result from a single Gemini topic expansion call."""

    parent_description: str   # broad summary - stored in topics.expanded_description
    subtopics: list[str]      # focused angles - each embedded and stored in topic_subtopics


class GeminiTopicExpander:
    """Small wrapper around Gemini for semantic topic expansion."""

    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    def expand_topic(self, name: str, description: str | None = None) -> TopicExpansionResult:
        prompt = f"""You expand user-created monitoring topics for semantic search.

Topic name: {name}
Topic description: {description or "None provided"}

Task:
1. Write a parent_description: one concise paragraph that broadly summarises the topic,
   covering its main themes, key entities, synonyms, and adjacent concepts.
   Preserve the user's intent.

2. Write subtopics: a list of focused descriptions, each capturing one specific angle,
   branch, or sub-area of the topic. Decide the number yourself based on how broad the
   topic is - generate between 3 and 15 subtopics.

   CRITICAL - writing style for subtopics:
   This system monitors LIVE news feeds. Subtopics will be matched against
   real news articles published today. Write accordingly.

   Write each subtopic in PRESENT tense, as if the events are happening RIGHT NOW.
   Use the kind of language that appears in current journalism: named entities,
   active verbs, specific ongoing situations, real organisations, concrete actions.
   Do NOT write about historical events or past incidents unless the topic is
   explicitly about history.

   Bad (historical):  "World War II ignites across Europe. Allied forces launch D-Day invasion."
   Bad (academic):    "Regulatory frameworks governing algorithmic decision-making systems."
   Good (journalistic, present): "Russia intensifies strikes on eastern Ukraine as NATO
   summit convenes. Western allies debate sending additional weapons to Kyiv."
   Good (journalistic, present): "Government passes AI safety law. Regulators fine tech
   companies for biased algorithms. EU AI Act takes effect, companies face compliance deadlines."

   Each subtopic should read like 2-3 short news sentences covering that angle RIGHT NOW.

If the user provided a description with hints, keywords, or specific areas they care
about, factor those into both outputs.

Return your answer as a JSON object with exactly these two keys:
{{
  "parent_description": "<single paragraph>",
  "subtopics": ["<subtopic 1>", "<subtopic 2>", ...]
}}

Do not include any text outside the JSON object. No markdown, no code fences, no labels."""

        try:
            response = self._client.models.generate_content(
                model=_MODEL,
                contents=prompt,
            )
            raw = (response.text or "").strip()
        except Exception as exc:  # pragma: no cover - provider/network failures
            raise TopicExpansionError(f"Gemini API error: {exc}") from exc

        if not raw:
            raise TopicExpansionError("Gemini returned an empty response.")

        # Strip markdown code fences - models sometimes wrap JSON in ```json ... ```
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TopicExpansionError(
                f"Gemini returned invalid JSON: {exc}\nRaw response: {raw[:300]}"
            ) from exc

        parent_description = (data.get("parent_description") or "").strip()
        subtopics = [s.strip() for s in (data.get("subtopics") or []) if s.strip()]

        if not parent_description:
            raise TopicExpansionError("Gemini returned an empty parent_description.")
        if not subtopics:
            raise TopicExpansionError("Gemini returned no subtopics.")

        return TopicExpansionResult(
            parent_description=parent_description,
            subtopics=subtopics,
        )


@lru_cache
def get_topic_expander() -> GeminiTopicExpander:
    """Return a cached Gemini client instance."""
    settings = get_settings()
    return GeminiTopicExpander(api_key=settings.gemini_api_key)
