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

2. Write subtopics: a list of focused subdomain descriptions, each capturing one specific angle,
   branch, or sub-area of the topic. Generate between 3 and 15 subtopics depending on how broad the topic is.

   CRITICAL - writing style for subtopics:
   This system monitors LIVE news feeds. Subtopics will be matched against
   real news articles published today. 
   Write them as descriptive domain specific phrases, not questions or single words.
   Use natural phrasing that mirrors how articles discuss the topic—include main subjects, actions, and qualifiers.
   they should be not be very short make them 20 to 30 words. 

   **Example for few Subdomains in AI**:
- The rapid development and deployment of Generative AI systems and Large Language Models by major tech companies, focusing on their increasing capabilities in natural language understanding, reasoning, and multi-modal generation.
- The broader impact of artificial intelligence on the global economy, specifically highlighting the ongoing automation of cognitive tasks, significant shifts in the labor market, and concerns about widespread job displacement across various industries.
- The massive surge in capital expenditure by technology giants investing heavily in specialized AI infrastructure, building next-generation data centers, and procuring advanced semiconductor chips to power artificial intelligence training and inference.
- The ongoing international debates among lawmakers and policymakers regarding the implementation of comprehensive regulatory frameworks, safety standards, and ethical guidelines designed to govern the development and mitigate the risks of advanced artificial intelligence.

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
