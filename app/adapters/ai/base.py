"""Ports and shared errors for the AI adapters.

EmbeddingInterface lives here rather than in app/pipeline/interfaces.py
because the pipeline is no longer the only caller — the API embeds topic
descriptions too. Keeping the contract next to its implementations means
there is exactly one definition of it; app/pipeline/interfaces.py re-exports
this symbol so pipeline code keeps importing from where it always did.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class EmbeddingGenerationError(Exception):
    """Raised when embedding generation fails, locally or remotely."""


class EmbeddingInterface(ABC):
    """Turn text into a vector. Implemented locally and over HTTP."""

    @abstractmethod
    def encode_text(self, text: str) -> List[float]:
        """Convert text into an embedding vector (768 dimensions)."""

    @abstractmethod
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """Convert several texts in one call, preserving input order."""


class LLMInterface(ABC):
    """Summarise an article. Implemented by the Groq adapter."""

    @abstractmethod
    def generate_summary(self, headline: str, content: str) -> str:
        """Generate a 2-3 sentence neutral summary of the article."""
