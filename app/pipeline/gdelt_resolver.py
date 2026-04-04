import os
import json
from pathlib import Path
import numpy as np
from typing import List, Tuple
from sentence_transformers import SentenceTransformer

class GDELTThemeResolver:
    """
    Utility to map expanded topic descriptions to GDELT GKG themes 
    using the pre-built semantic vector index.
    """
    
    def __init__(self, index_dir: str = "scripts/gdelt_theme_index"):
        self.index_dir = Path(index_dir)
        self.themes_file = self.index_dir / "themes.json"
        self.indexed_list_file = self.index_dir / "indexed_themes.json"
        self.vectors_file = self.index_dir / "vectors.npy"
        
        self.themes: List[str] = []
        self.vectors: np.ndarray = np.empty((0, 0))
        self.model = None
        
        # Load index on demand (lazy loading)
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
            
        if not self.vectors_file.exists():
            raise FileNotFoundError(
                f"GDELT Vectors not found in {self.index_dir}. "
                "Please run scripts/run_gdelt_embedding.py first."
            )
            
        # Priority: use the indexed_themes.json which matches the vectors
        if self.indexed_list_file.exists():
            self.themes = json.loads(self.indexed_list_file.read_text())
        elif self.themes_file.exists():
            self.themes = json.loads(self.themes_file.read_text())
        else:
            raise FileNotFoundError("Theme list not found.")

        self.vectors = np.load(str(self.vectors_file))
        
        # Final catch for size mismatch
        if len(self.themes) != self.vectors.shape[0]:
            self.themes = self.themes[:self.vectors.shape[0]]
        
        # Load local embedding model
        print("[GDELTResolver] Loading sentence-transformers model...")
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self._loaded = True
        print("[GDELTResolver] Ready.")

    def resolve(self, expanded_topic_text: str, top_n: int = 5) -> List[Tuple[str, float]]:
        """
        Takes a rich topic description (paragraph) and returns the top N 
        matching GDELT theme IDs and their cosine similarity scores.
        """
        self._ensure_loaded()
        
        # 1. Embed the topic expansion
        query_vec = self.model.encode(expanded_topic_text, normalize_embeddings=True)
        
        # 2. Calculate cosine similarities (vectors are already L2-normalized)
        # Handle cases where index might be empty or smaller than N
        current_size = self.vectors.shape[0]
        if current_size == 0:
            return []
            
        scores = self.vectors @ query_vec
        
        # 3. Get top N
        actual_n = min(top_n, current_size)
        top_indices = scores.argsort()[::-1][:actual_n]
        
        results = [
            (self.themes[idx], float(scores[idx])) 
            for idx in top_indices
        ]
        
        return results

    def get_query_themes(self, expanded_topic_text: str, score_threshold: float = 0.5) -> List[str]:
        """
        Returns just the theme IDs that match above a certain quality threshold.
        Used to generate the GDELT API query string.
        """
        matches = self.resolve(expanded_topic_text)
        return [theme for theme, score in matches if score >= score_threshold]
