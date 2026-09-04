"""Local Sentence-BERT embedding adapter.

This replaces the two near-identical copies that used to live in
app/core/embeddings.py (API side) and app/pipeline/adapters/embedding_adapter.py
(pipeline side). They had drifted: only the pipeline copy set HF_HUB_OFFLINE,
so the API container could still reach out to HuggingFace at runtime.

Only the embedding-service container loads this class now. Everything else
talks to that service through EmbeddingClient (see client.py).
"""

from __future__ import annotations

import os

# Force sentence-transformers (and huggingface_hub under the hood) to run
# completely offline. Prevents unauthenticated requests, telemetry, and HEAD
# pings for updates. The model is baked into the image at build time, so a
# cache miss here should fail loudly rather than silently download.
os.environ["HF_HUB_OFFLINE"] = "1"

from functools import lru_cache
from typing import List

from sentence_transformers import SentenceTransformer

from app.adapters.ai.errors import EmbeddingGenerationError
from app.pipeline.interfaces import EmbeddingInterface

MODEL_NAME = "all-mpnet-base-v2"


class SentenceBertEmbedder(EmbeddingInterface):
    """
    Generate 768-dimensional embeddings using all-mpnet-base-v2.

    General-purpose MPNet model. Benchmarked against 4 other models (384-dim
    and 768-dim variants); achieved the highest Top-1 accuracy (87%) and best
    Recall@0.65 (5%) for topic-to-article matching. Runs entirely offline from
    the local HuggingFace cache.
    """

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self.model = SentenceTransformer(model_name)

    def encode_text(self, text: str) -> List[float]:
        # DO NOT add normalize_embeddings=True here. It was tried and reverted.
        #
        # Every comparison in this codebase is cosine, which is scale-invariant,
        # so normalising changes vector DIRECTIONS by at most ~1.5e-08. But
        # UMAP+HDBSCAN at this dataset size is chaotically sensitive to input
        # perturbation: that 1.5e-08 was enough to flip one benchmark topic from
        # 7 clusters / 92% purity / 100% recall to 2 / 50% / 25%, reproducibly.
        # See docs/discovery-accuracy-log.md v3.
        #
        # The change had a theoretical rationale (centroid means are unweighted,
        # so unequal norms tilt them) and no measurable benefit, so it is not
        # worth perturbing clustering for.
        try:
            embedding = self.model.encode(text)
        except Exception as exc:  # pragma: no cover - model/runtime failures
            raise EmbeddingGenerationError(f"Embedding generation failed: {exc}") from exc

        return embedding.tolist()

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Encode several texts in one call — as a LOOP of single encodes, not a
        batched model.encode([...]).

        This is deliberate and is not an oversight. Batched encoding pads every
        input to the longest sequence in the batch, and the padded forward pass
        does not produce bit-identical vectors to encoding the same text alone.
        Given how sensitive the downstream clustering is (see the note in
        encode_text), a vector must not depend on which other articles happened
        to arrive in the same claim batch.

        The win we actually wanted from batching is one HTTP round trip instead
        of ten — that is a transport concern, and this method still delivers it.
        The model call stays one-at-a-time so the numbers never move.
        """
        return [self.encode_text(text) for text in texts]


@lru_cache
def get_local_embedder() -> SentenceBertEmbedder:
    """Return the process-wide Sentence-BERT instance, loading it on first call."""
    return SentenceBertEmbedder()
