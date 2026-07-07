import json
import logging
from dataclasses import dataclass, field
import numpy as np

logger = logging.getLogger(__name__)

def _parse_pgvector(vec_str: str) -> list[float]:
    """Convert pgvector string '[0.1,0.2,...]' to List[float]."""
    return json.loads(vec_str)

def _to_pgvector(embedding: np.ndarray | list[float]) -> str:
    """Convert a numpy array or list to pgvector literal '[f1,f2,...]'."""
    if isinstance(embedding, np.ndarray):
        return "[" + ",".join(str(float(x)) for x in embedding) + "]"
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"

def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D numpy arrays."""
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)

def _extract_keywords(headlines: list[str], top_n: int = 10) -> list[str]:
    """
    Extract the top N most-frequent non-stopword tokens from a list of headlines.
    """
    STOP_WORDS = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "is", "was", "are", "were", "be", "been",
        "has", "have", "had", "it", "its", "as", "by", "from", "that",
        "this", "they", "their", "will", "says", "say", "said", "after",
        "new", "over", "up", "out", "into", "than", "more", "about",
    }
    word_counts: dict[str, int] = {}
    for headline in headlines:
        for word in headline.lower().split():
            token = word.strip(".,!?;:\"'()-")
            if token and token not in STOP_WORDS and len(token) > 2:
                word_counts[token] = word_counts.get(token, 0) + 1

    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:top_n]]

@dataclass
class _ArticleRow:
    id: str
    embedding: np.ndarray
    headline: str

@dataclass
class _SubThemeData:
    label: int                            # HDBSCAN cluster label (0..N)
    members: list[_ArticleRow] = field(default_factory=list)
    centroid: np.ndarray | None = None
    anchor_embeddings: list[np.ndarray] = field(default_factory=list)
    representative_article_id: str | None = None
    keywords: list[str] = field(default_factory=list)
    reddit_post_ids: list[str] = field(default_factory=list)
    reddit_post_count: int = 0
    sentiment_score: float | None = None
    # Set during Step 4
    sub_theme_id: str | None = None
    is_new: bool = True
    should_relabel: bool = True
    label_text: str | None = None
    description_text: str | None = None
    status: str = "emerging"
    events: list[str] = field(default_factory=list)
    snapshot_id: str | None = None
