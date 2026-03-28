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
    Default Model: all-MiniLM-L6-v2 which generates a 384 dimensional vector.
    Runs entirely offline using the local HuggingFace cache.
    """
    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        self.model = SentenceTransformer(model_name)
        
    def encode_text(self, text: str) -> List[float]:
        # Returns a numpy array by default, but we should return List[float]
        return self.model.encode(text).tolist()
