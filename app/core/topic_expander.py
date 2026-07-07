"""Groq client for topic expansion on the API side."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from groq import Groq

from app.config import get_settings

logger = logging.getLogger(__name__)

_MODEL = "llama-3.1-8b-instant"


class TopicExpansionError(Exception):
    """Raised when topic expansion via Groq fails."""


@dataclass
class TopicExpansionResult:
    """Structured result from a single topic expansion call."""

    parent_description: str   # broad summary - stored in topics.expanded_description
    subtopics: list[str]      # focused angles - each embedded and stored in topic_subtopics


class GroqTopicExpander:
    """Small wrapper around Groq for semantic topic expansion."""

    def __init__(self, api_key: str, model_name: str = _MODEL) -> None:
        self._client = Groq(api_key=api_key)
        self._model = model_name

    def expand_topic(self, name: str, description: str | None = None) -> TopicExpansionResult:
        prompt = f"""You expand user-created monitoring topics for semantic search.

Topic name: {name}
Topic description: {description or "None provided"}

Task:
1. Write a parent_description: one concise paragraph that broadly summarises the topic,
   covering its main themes, key entities, synonyms, and adjacent concepts.
   Preserve the user's intent.

2. Write subtopics: a list of focused subdomain descriptions, each capturing one specific angle,
   branch, or sub-area of the topic. Generate between 3 and 6 subtopics depending on how broad the topic is.

   CRITICAL - writing style for subtopics:
   This system monitors LIVE news feeds. Subtopics will be matched against
   real news articles published today.
   Write them as descriptive domain specific phrases, not questions or single words.
   Use natural phrasing that mirrors how articles discuss the topic—include main subjects, actions, and qualifiers.
   they should be not be very short make them 20 to 30 words.

   MOST IMPORTANT - If the user uses some named entaties in the topic name like American politics or Indian cricket or Chatgpt advnacements, then make sure that the subtopics and parent_description also must contain those named entities and related named entities heavily. For example if the topic is about Indian cricket, then the subtopics should also be about Indian cricket and related terms like IPL, Diffrent IPL team names, players etc and NOT just general terms like sports.

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
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = (response.choices[0].message.content or "").strip()
        except Exception as exc:  # pragma: no cover - provider/network failures
            logger.error("Groq API call failed: %s", exc, exc_info=True)
            raise TopicExpansionError(f"Groq API error: {exc}") from exc

        if not raw:
            raise TopicExpansionError("Groq returned an empty response.")

        # Strip markdown code fences - models sometimes wrap JSON in ```json ... ```
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TopicExpansionError(
                f"Groq returned invalid JSON: {exc}\nRaw response: {raw[:300]}"
            ) from exc

        parent_description = (data.get("parent_description") or "").strip()
        subtopics = [s.strip() for s in (data.get("subtopics") or []) if s.strip()]

        if not parent_description:
            raise TopicExpansionError("Groq returned an empty parent_description.")
        if not subtopics:
            raise TopicExpansionError("Groq returned no subtopics.")

        return TopicExpansionResult(
            parent_description=parent_description,
            subtopics=subtopics,
        )


@lru_cache
def get_topic_expander() -> GroqTopicExpander:
    """Return a cached Groq client instance."""
    settings = get_settings()
    return GroqTopicExpander(api_key=settings.groq_api_key)
