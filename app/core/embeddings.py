"""Sentence-BERT embedding utilities for the API side."""

from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer


class EmbeddingGenerationError(Exception):
    """Raised when text embedding generation fails."""


class SentenceBertEmbedder:
    """Generate 768-dimensional embeddings using all-mpnet-base-v2.

    General-purpose MPNet model producing 768-dim vectors. Benchmarked against
    4 other models (384-dim and 768-dim variants); achieved the highest Top-1
    accuracy (87%) and best Recall@0.65 (5%) for topic-to-article matching.
    """

    def __init__(self, model_name: str = "all-mpnet-base-v2") -> None:
        self.model = SentenceTransformer(model_name)

    def encode_text(self, text: str) -> list[float]:
        try:
            embedding = self.model.encode(text)
        except Exception as exc:  # pragma: no cover - model/runtime failures
            raise EmbeddingGenerationError(f"Embedding generation failed: {exc}") from exc

        return embedding.tolist()


@lru_cache
def get_embedder() -> SentenceBertEmbedder:
    """Return a cached Sentence-BERT model instance."""
    return SentenceBertEmbedder()
