import os
# Force sentence-transformers (and huggingface_hub under the hood) to run completely offline.
# Prevents unauthenticated requests, telemetry, and HEAD pings for updates.
os.environ["HF_HUB_OFFLINE"] = "1"

from sentence_transformers import SentenceTransformer
from app.pipeline.interfaces import EmbeddingInterface
from typing import List

class SentenceBertAdapter(EmbeddingInterface):
    """
    Implements local sentence embedding using HuggingFace's sentence-transformers.
    Model: all-mpnet-base-v2 — 768-dim general-purpose MPNet model. Benchmarked
    against 4 alternatives; achieved 87% Top-1 accuracy and best Recall@0.65
    for topic-to-article matching. Runs entirely offline using the local HuggingFace cache.
    """
    def __init__(self, model_name: str = 'all-mpnet-base-v2'):
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
        # Returns a numpy array by default, but we should return List[float]
        return self.model.encode(text).tolist()
