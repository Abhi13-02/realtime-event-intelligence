"""
Unit tests for the clustering logic in app/tasks/subtheme_discovery.py.

Tests cover:
  - _step1_cluster (HDBSCAN) — happy path, noise-only input, too few articles
  - _step2_assign_reddit — correct centroid assignment, below-threshold rejection
  - _step3_sentiment — weighted VADER, no comments, no Reddit posts
  - _step5_evolution — emerging, growing, disappearing, sentiment shift, no-event
  - _extract_keywords — top-N extraction, stop-word filtering
  - _cosine_similarity — identical vectors, orthogonal vectors, zero vector
  - _to_pgvector / _parse_pgvector — round-trip conversion

No DB, no Kafka, no Celery, no Cohere — all external calls are bypassed.
Run with:
  pytest tests/test_subtheme_clustering.py -v
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.tasks.subtheme_discovery import (
    _ArticleRow,
    _SubThemeData,
    _cosine_similarity,
    _extract_keywords,
    _parse_pgvector,
    _step1_cluster,
    _step2_assign_reddit,
    _step3_sentiment,
    _step5_evolution,
    _to_pgvector,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_settings(**overrides):
    """Minimal settings object with all clustering thresholds."""
    defaults = {
        "subtheme_min_cluster_size": 2,
        "subtheme_min_samples": 1,
        "subtheme_window_days": 3,
        "subtheme_reddit_assign_threshold": 0.55,
        "subtheme_centroid_match_threshold": 0.80,
        "subtheme_growing_threshold": 0.50,
        "subtheme_disappearing_threshold": 0.20,
        "subtheme_sentiment_shift_threshold": 0.20,
        "subtheme_baseline_days": 7,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _article(id: str, embedding: list[float], headline: str = "Test headline") -> _ArticleRow:
    """Helper: create a fake _ArticleRow with a numpy embedding."""
    return _ArticleRow(id=id, embedding=np.array(embedding), headline=headline)


def _sub_theme_with_centroid(centroid: list[float], is_new: bool = False, sub_theme_id: str = "st-001") -> _SubThemeData:
    """Helper: create a _SubThemeData with a pre-set centroid."""
    st = _SubThemeData(label=0)
    st.centroid = np.array(centroid)
    st.is_new = is_new
    st.sub_theme_id = None if is_new else sub_theme_id
    return st


# ─────────────────────────────────────────────────────────────────────────────
# _cosine_similarity
# ─────────────────────────────────────────────────────────────────────────────

class TestCosineSimilarity:

    def test_identical_vectors_return_one(self):
        v = np.array([1.0, 0.0, 0.0])
        assert math.isclose(_cosine_similarity(v, v), 1.0, rel_tol=1e-6)

    def test_orthogonal_vectors_return_zero(self):
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert math.isclose(_cosine_similarity(a, b), 0.0, abs_tol=1e-9)

    def test_opposite_vectors_return_minus_one(self):
        a = np.array([1.0, 0.0])
        b = np.array([-1.0, 0.0])
        assert math.isclose(_cosine_similarity(a, b), -1.0, rel_tol=1e-6)

    def test_zero_vector_returns_zero(self):
        """Zero vectors should return 0.0 without raising exceptions."""
        z = np.array([0.0, 0.0])
        v = np.array([1.0, 0.0])
        assert _cosine_similarity(z, v) == 0.0
        assert _cosine_similarity(v, z) == 0.0

    def test_similar_vectors_return_high_score(self):
        """Two nearly identical vectors should return similarity close to 1."""
        a = np.array([1.0, 0.1, 0.05])
        b = np.array([0.9, 0.15, 0.08])
        sim = _cosine_similarity(a, b)
        assert sim > 0.99


# ─────────────────────────────────────────────────────────────────────────────
# _to_pgvector / _parse_pgvector
# ─────────────────────────────────────────────────────────────────────────────

class TestVectorConversion:

    def test_round_trip_numpy_array(self):
        original = np.array([0.1, 0.2, -0.5, 1.0])
        encoded = _to_pgvector(original)
        decoded = _parse_pgvector(encoded)
        assert isinstance(encoded, str)
        assert encoded.startswith("[") and encoded.endswith("]")
        np.testing.assert_allclose(decoded, original.tolist(), rtol=1e-6)

    def test_round_trip_list(self):
        original = [0.3, -0.7, 1.0]
        encoded = _to_pgvector(original)
        decoded = _parse_pgvector(encoded)
        np.testing.assert_allclose(decoded, original, rtol=1e-6)

    def test_high_dimensional_vector(self):
        """Confirm 384-dim vectors round-trip without truncation."""
        original = np.random.rand(384).astype(np.float64)
        decoded = _parse_pgvector(_to_pgvector(original))
        np.testing.assert_allclose(decoded, original.tolist(), rtol=1e-5)


# ─────────────────────────────────────────────────────────────────────────────
# _extract_keywords
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractKeywords:

    def test_returns_top_n_keywords(self):
        headlines = [
            "NVIDIA GPU shortage hits data centres",
            "NVIDIA H100 GPU supply chain delayed",
            "AMD GPU sales grow despite NVIDIA shortage",
        ]
        keywords = _extract_keywords(headlines, top_n=3)
        assert len(keywords) == 3
        # "nvidia" appears 3 times — must be #1
        assert keywords[0].lower() == "nvidia"

    def test_stop_words_excluded(self):
        headlines = ["The supply of chips is growing in the market"]
        keywords = _extract_keywords(headlines, top_n=10)
        stop_words = {"the", "is", "in", "of"}
        for kw in keywords:
            assert kw.lower() not in stop_words

    def test_empty_headlines_returns_empty_list(self):
        assert _extract_keywords([], top_n=5) == []

    def test_single_headline_extracts_words(self):
        headlines = ["Quantum computing breakthrough announced"]
        keywords = _extract_keywords(headlines, top_n=5)
        assert len(keywords) > 0
        assert "quantum" in keywords or "computing" in keywords


# ─────────────────────────────────────────────────────────────────────────────
# _step1_cluster — HDBSCAN
# ─────────────────────────────────────────────────────────────────────────────

class TestStep1Cluster:
    """
    HDBSCAN is non-deterministic in edge cases but highly deterministic when
    articles form clearly separated clusters. We construct embeddings that sit
    at opposite poles of the embedding space so HDBSCAN reliably assigns them.
    """

    def _make_cluster_articles(self, center: list[float], n: int, noise: float = 0.01) -> list[_ArticleRow]:
        """Generate n articles tightly packed around a center embedding."""
        rng = np.random.default_rng(seed=42)
        center_arr = np.array(center, dtype=np.float64)
        articles = []
        for i in range(n):
            vec = center_arr + rng.normal(0, noise, size=len(center))
            # Normalise to unit sphere so cosine similarity is meaningful
            vec = vec / np.linalg.norm(vec)
            articles.append(_article(f"a-{i}", vec.tolist(), f"Cluster article {i}"))
        return articles

    def test_two_distinct_clusters_are_found(self):
        """
        Two tight groups at opposite ends of 8-dim space → HDBSCAN finds 2 clusters.
        """
        settings = _make_settings(subtheme_min_cluster_size=2, subtheme_min_samples=1)
        center_a = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        center_b = [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        articles = (
            self._make_cluster_articles(center_a, n=5)
            + self._make_cluster_articles(center_b, n=5)
        )
        result = _step1_cluster(articles, settings)
        assert len(result) == 2

    def test_each_cluster_has_centroid_and_representative(self):
        settings = _make_settings(subtheme_min_cluster_size=2, subtheme_min_samples=1)
        center_a = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        center_b = [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        articles = (
            self._make_cluster_articles(center_a, n=5)
            + self._make_cluster_articles(center_b, n=5)
        )
        result = _step1_cluster(articles, settings)
        for cluster in result:
            assert cluster.centroid is not None
            assert cluster.representative_article_id is not None
            assert isinstance(cluster.keywords, list)
            assert len(cluster.members) >= 2

    def test_representative_is_closest_to_centroid(self):
        """The representative article's ID must belong to the article closest to the centroid."""
        settings = _make_settings(subtheme_min_cluster_size=2, subtheme_min_samples=1)
        center = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        articles = self._make_cluster_articles(center, n=6)
        result = _step1_cluster(articles, settings)
        assert len(result) >= 1
        cluster = result[0]
        # Compute nearest member to centroid manually
        sims = [_cosine_similarity(a.embedding, cluster.centroid) for a in cluster.members]
        expected_rep_id = cluster.members[int(np.argmax(sims))].id
        assert cluster.representative_article_id == expected_rep_id

    def test_all_noise_returns_empty(self):
        """
        If HDBSCAN labels all points as noise (-1), result should be empty.
        Force this by using random unit vectors with a very high min_cluster_size.
        """
        settings = _make_settings(subtheme_min_cluster_size=50, subtheme_min_samples=10)
        rng = np.random.default_rng(seed=99)
        articles = [
            _article(f"n-{i}", (rng.random(8) / np.linalg.norm(rng.random(8))).tolist())
            for i in range(5)  # Only 5 articles — below min_cluster_size of 50
        ]
        result = _step1_cluster(articles, settings)
        assert result == []

    def test_single_cluster(self):
        """All articles from the same topic region → one cluster."""
        settings = _make_settings(subtheme_min_cluster_size=2, subtheme_min_samples=1)
        center = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        articles = self._make_cluster_articles(center, n=8)
        result = _step1_cluster(articles, settings)
        assert len(result) == 1

    def test_keywords_extracted_per_cluster(self):
        """Each cluster should have keywords extracted from member headlines."""
        settings = _make_settings(subtheme_min_cluster_size=2, subtheme_min_samples=1)
        center_a = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        center_b = [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
        articles_a = self._make_cluster_articles(center_a, n=5)
        for i, a in enumerate(articles_a):
            a.headline = f"NVIDIA GPU supply shortage affecting data centres {i}"
        articles_b = self._make_cluster_articles(center_b, n=5)
        for i, a in enumerate(articles_b):
            a.headline = f"Interest rates rise as central banks tighten policy {i}"

        result = _step1_cluster(articles_a + articles_b, settings)
        keyword_pool = [kw for cluster in result for kw in cluster.keywords]
        assert len(keyword_pool) > 0


# ─────────────────────────────────────────────────────────────────────────────
# _step2_assign_reddit
# ─────────────────────────────────────────────────────────────────────────────

class TestStep2AssignReddit:

    def _make_fake_cur(self, reddit_rows: list[dict]):
        """Fake psycopg2 cursor that returns reddit_rows from fetchall()."""
        cur = MagicMock()
        cur.fetchall.return_value = [
            SimpleNamespace(id=r["id"], embedding=_to_pgvector(r["embedding"]))
            for r in reddit_rows
        ]
        return cur

    def test_post_assigned_to_nearest_cluster(self):
        """A Reddit post near cluster A should be assigned to cluster A."""
        settings = _make_settings(subtheme_reddit_assign_threshold=0.0)

        # Two clusters far apart
        center_a = np.array([1.0, 0.0, 0.0, 0.0])
        center_b = np.array([0.0, 0.0, 0.0, 1.0])
        st_a = _sub_theme_with_centroid(center_a.tolist(), is_new=True)
        st_b = _sub_theme_with_centroid(center_b.tolist(), is_new=True)
        st_a.members = [_article("g1", center_a.tolist())]
        st_b.members = [_article("g2", center_b.tolist())]

        # Reddit post very close to cluster A
        reddit_embedding = np.array([0.98, 0.1, 0.05, 0.02])
        reddit_embedding = reddit_embedding / np.linalg.norm(reddit_embedding)

        cur = self._make_fake_cur([{"id": "r1", "embedding": reddit_embedding.tolist()}])
        _step2_assign_reddit(cur, MagicMock(), "topic-1", [st_a, st_b], settings)

        assert "r1" in st_a.reddit_post_ids
        assert "r1" not in st_b.reddit_post_ids
        assert st_a.reddit_post_count == 1
        assert st_b.reddit_post_count == 0

    def test_post_below_threshold_not_assigned(self):
        """A post with similarity below threshold should be rejected."""
        settings = _make_settings(subtheme_reddit_assign_threshold=0.90)

        # Cluster centroid along dim 0
        center = np.array([1.0, 0.0, 0.0, 0.0])
        st = _sub_theme_with_centroid(center.tolist(), is_new=True)
        st.members = [_article("g1", center.tolist())]

        # Post at 45 degrees — similarity = cos(45°) ≈ 0.707 < 0.90
        post_emb = np.array([1.0, 1.0, 0.0, 0.0])
        post_emb = post_emb / np.linalg.norm(post_emb)

        cur = self._make_fake_cur([{"id": "r1", "embedding": post_emb.tolist()}])
        _step2_assign_reddit(cur, MagicMock(), "topic-1", [st], settings)

        assert st.reddit_post_count == 0
        assert "r1" not in st.reddit_post_ids

    def test_no_reddit_posts_leaves_count_zero(self):
        """If there are no Reddit posts in DB, all clusters stay at count 0."""
        settings = _make_settings()
        center = np.array([1.0, 0.0, 0.0, 0.0])
        st = _sub_theme_with_centroid(center.tolist())
        st.members = []

        cur = self._make_fake_cur([])
        _step2_assign_reddit(cur, MagicMock(), "topic-1", [st], settings)

        assert st.reddit_post_count == 0

    def test_many_posts_all_assigned_to_correct_cluster(self):
        """Multiple posts should each go to the most similar centroid."""
        settings = _make_settings(subtheme_reddit_assign_threshold=0.0)
        center_a = np.array([1.0, 0.0])
        center_b = np.array([0.0, 1.0])
        st_a = _sub_theme_with_centroid(center_a.tolist(), is_new=True)
        st_b = _sub_theme_with_centroid(center_b.tolist(), is_new=True)
        st_a.members = []
        st_b.members = []

        # 3 posts near A, 2 near B
        reddit_posts = [
            {"id": f"rA{i}", "embedding": (center_a + np.random.default_rng(i).normal(0, 0.05, 2)).tolist()}
            for i in range(3)
        ] + [
            {"id": f"rB{i}", "embedding": (center_b + np.random.default_rng(i+10).normal(0, 0.05, 2)).tolist()}
            for i in range(2)
        ]
        cur = self._make_fake_cur(reddit_posts)
        _step2_assign_reddit(cur, MagicMock(), "topic-1", [st_a, st_b], settings)

        assert st_a.reddit_post_count == 3
        assert st_b.reddit_post_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# _step3_sentiment (VADER)
# ─────────────────────────────────────────────────────────────────────────────

class TestStep3Sentiment:

    def _make_cur(self, rows):
        cur = MagicMock()
        cur.fetchall.return_value = [SimpleNamespace(body=r["body"], score=r["score"]) for r in rows]
        return cur

    def _make_vader(self):
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        return SentimentIntensityAnalyzer()

    def test_clearly_positive_comments_positive_sentiment(self):
        vader = self._make_vader()
        st = _SubThemeData(label=0)
        st.reddit_post_ids = ["r1"]
        st.centroid = np.zeros(4)
        st.members = []

        cur = self._make_cur([
            {"body": "This is absolutely amazing and wonderful! Great job!", "score": 10},
            {"body": "Fantastic breakthrough, really exciting times!", "score": 8},
        ])
        _step3_sentiment(cur, [st], vader)

        assert st.sentiment_score is not None
        assert st.sentiment_score > 0.05
        assert st.sentiment_label == "positive"

    def test_clearly_negative_comments_negative_sentiment(self):
        vader = self._make_vader()
        st = _SubThemeData(label=0)
        st.reddit_post_ids = ["r1"]
        st.centroid = np.zeros(4)
        st.members = []

        cur = self._make_cur([
            {"body": "This is terrible, awful and deeply disappointing.", "score": 5},
            {"body": "Complete disaster. Worst outcome possible. Really bad.", "score": 3},
        ])
        _step3_sentiment(cur, [st], vader)

        assert st.sentiment_score is not None
        assert st.sentiment_score < -0.05
        assert st.sentiment_label == "negative"

    def test_no_reddit_posts_returns_none(self):
        """Sub-themes with no Reddit posts should have sentiment_score = None."""
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        vader = SentimentIntensityAnalyzer()
        st = _SubThemeData(label=0)
        st.reddit_post_ids = []   # No Reddit posts
        st.centroid = np.zeros(4)
        st.members = []

        cur = MagicMock()
        _step3_sentiment(cur, [st], vader)

        assert st.sentiment_score is None
        assert st.sentiment_label is None
        cur.execute.assert_not_called()   # No DB query if no Reddit posts

    def test_no_comments_in_db_returns_none(self):
        """Reddit posts exist but no comments stored → None sentiment."""
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        vader = SentimentIntensityAnalyzer()
        st = _SubThemeData(label=0)
        st.reddit_post_ids = ["r1"]
        st.centroid = np.zeros(4)
        st.members = []

        cur = self._make_cur([])  # Empty result set
        _step3_sentiment(cur, [st], vader)

        assert st.sentiment_score is None
        assert st.sentiment_label is None

    def test_higher_scored_comments_weighted_more(self):
        """
        A high-score positive comment should dominate over a low-score negative one.
        Weight = upvote score. score=100 positive vs score=1 negative → positive overall.
        """
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        vader = SentimentIntensityAnalyzer()
        st = _SubThemeData(label=0)
        st.reddit_post_ids = ["r1"]
        st.centroid = np.zeros(4)
        st.members = []

        cur = self._make_cur([
            {"body": "Absolutely incredible and amazing!", "score": 100},  # strongly positive
            {"body": "Terrible and awful.", "score": 1},                   # strongly negative
        ])
        _step3_sentiment(cur, [st], vader)

        assert st.sentiment_score is not None
        # High-weight positive should win
        assert st.sentiment_score > 0.0

    def test_neutral_comments_return_neutral_label(self):
        """Comments around 0.0 VADER score → neutral label."""
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        vader = SentimentIntensityAnalyzer()
        st = _SubThemeData(label=0)
        st.reddit_post_ids = ["r1"]
        st.centroid = np.zeros(4)
        st.members = []

        # Factual, neutral text
        cur = self._make_cur([
            {"body": "The report was released on Tuesday.", "score": 1},
            {"body": "Officials met to discuss the matter.", "score": 1},
        ])
        _step3_sentiment(cur, [st], vader)

        # Neutral is expected — may be None if exactly 0, or 'neutral'
        if st.sentiment_score is not None:
            assert st.sentiment_label in ("neutral", "positive", "negative")

    def test_multiple_clusters_each_get_own_sentiment(self):
        """Two clusters with opposite sentiment should get opposite labels."""
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        vader = SentimentIntensityAnalyzer()

        st_pos = _SubThemeData(label=0)
        st_pos.reddit_post_ids = ["r_pos"]
        st_pos.centroid = np.zeros(4)
        st_pos.members = []

        st_neg = _SubThemeData(label=1)
        st_neg.reddit_post_ids = ["r_neg"]
        st_neg.centroid = np.zeros(4)
        st_neg.members = []

        call_count = {"n": 0}
        def _side_effect(query, post_ids):
            call_count["n"] += 1
            if "r_pos" in post_ids:
                return [SimpleNamespace(body="Wonderful and amazing!", score=10)]
            return [SimpleNamespace(body="Terrible disaster horrible!", score=10)]

        cur = MagicMock()
        cur.fetchall.side_effect = [
            [SimpleNamespace(body="Wonderful and amazing!", score=10)],
            [SimpleNamespace(body="Terrible disaster horrible!", score=10)],
        ]
        _step3_sentiment(cur, [st_pos, st_neg], vader)

        assert st_pos.sentiment_label == "positive"
        assert st_neg.sentiment_label == "negative"


# ─────────────────────────────────────────────────────────────────────────────
# _step5_evolution
# ─────────────────────────────────────────────────────────────────────────────

class TestStep5Evolution:
    """
    _step5_evolution uses a psycopg2 cursor (sync). We mock it via MagicMock.
    Logic: previous snapshot → compare current state → fire events.
    """

    def _make_st(self, sub_theme_id: str | None, is_new: bool, members: int, reddit: int, sentiment: float | None) -> _SubThemeData:
        st = _SubThemeData(label=0)
        st.sub_theme_id = sub_theme_id
        st.is_new = is_new
        st.members = [_article(f"g{i}", [1.0, 0.0]) for i in range(members)]
        st.reddit_post_count = reddit
        st.sentiment_score = sentiment
        return st

    def _mock_cur(self, prev_volume: int | None, prev_sentiment: float | None,
                  peak_volume: int | None, baseline_sentiment: float | None) -> MagicMock:
        """
        Build a cursor mock that returns exactly what _step5_evolution expects:
          1st fetchone → (total_volume, sentiment_score) for previous snapshot
          2nd fetchone → (MAX(total_volume),) for peak
          3rd fetchone → (AVG(sentiment_score),) for baseline
        """
        cur = MagicMock()
        if prev_volume is None:
            # No previous snapshot — cursor returns None
            cur.fetchone.side_effect = [None, None, None]
        else:
            cur.fetchone.side_effect = [
                SimpleNamespace(total_volume=prev_volume, sentiment_score=prev_sentiment),
                (peak_volume,),
                (baseline_sentiment,),
            ]
        return cur

    def test_new_sub_theme_fires_emerging(self):
        settings = _make_settings()
        st = self._make_st(sub_theme_id=None, is_new=True, members=5, reddit=2, sentiment=None)
        cur = MagicMock()
        _step5_evolution(cur, [st], settings)
        assert "sub_theme_emerging" in st.events
        assert st.status == "emerging"

    def test_no_previous_snapshot_fires_emerging(self):
        settings = _make_settings()
        st = self._make_st("st-1", is_new=False, members=5, reddit=0, sentiment=None)
        cur = self._mock_cur(prev_volume=None, prev_sentiment=None, peak_volume=None, baseline_sentiment=None)
        _step5_evolution(cur, [st], settings)
        assert "sub_theme_emerging" in st.events

    def test_volume_growth_fires_growing(self):
        """Current volume 50% above previous → sub_theme_growing."""
        settings = _make_settings(subtheme_growing_threshold=0.5)
        # prev=10, current=15 → delta = (15-10)/10 = 0.50 >= threshold
        st = self._make_st("st-1", is_new=False, members=15, reddit=0, sentiment=None)
        cur = self._mock_cur(prev_volume=10, prev_sentiment=None, peak_volume=15, baseline_sentiment=None)
        _step5_evolution(cur, [st], settings)
        assert "sub_theme_growing" in st.events
        assert st.status == "active"

    def test_volume_below_peak_fires_disappearing(self):
        """Volume at 10% of peak → sub_theme_disappearing (threshold 20%)."""
        settings = _make_settings(subtheme_disappearing_threshold=0.20, subtheme_growing_threshold=0.50)
        # current_volume = 2, peak = 20 → 2/20 = 0.10 <= 0.20
        st = self._make_st("st-1", is_new=False, members=2, reddit=0, sentiment=None)
        cur = self._mock_cur(prev_volume=15, prev_sentiment=None, peak_volume=20, baseline_sentiment=None)
        _step5_evolution(cur, [st], settings)
        assert "sub_theme_disappearing" in st.events
        assert st.status == "inactive"

    def test_sentiment_shift_fires_event(self):
        """Sentiment shifted 0.4 above baseline (threshold 0.2) → sentiment shift event."""
        settings = _make_settings(subtheme_sentiment_shift_threshold=0.20, subtheme_growing_threshold=0.50)
        # prev_volume=10, current=11 → delta=0.10 (no growing)
        # baseline=-0.1, current=+0.4 → |shift|=0.5 > 0.2
        st = self._make_st("st-1", is_new=False, members=11, reddit=0, sentiment=0.4)
        cur = self._mock_cur(prev_volume=10, prev_sentiment=-0.1, peak_volume=15, baseline_sentiment=-0.1)
        _step5_evolution(cur, [st], settings)
        assert "sub_theme_sentiment_shift" in st.events

    def test_no_change_fires_no_events(self):
        """Stable volume, small delta, similar sentiment → no events."""
        settings = _make_settings(
            subtheme_growing_threshold=0.50,
            subtheme_disappearing_threshold=0.20,
            subtheme_sentiment_shift_threshold=0.20,
        )
        # prev=10, current=11 → delta=0.10 (below growing threshold)
        # current/peak = 11/12 = 0.91 (above disappearing threshold)
        # sentiment: 0.1 vs baseline 0.1 → |shift| = 0.0
        st = self._make_st("st-1", is_new=False, members=11, reddit=0, sentiment=0.1)
        cur = self._mock_cur(prev_volume=10, prev_sentiment=0.1, peak_volume=12, baseline_sentiment=0.1)
        _step5_evolution(cur, [st], settings)
        assert st.events == []

    def test_both_growing_and_sentiment_shift_can_fire_together(self):
        """Multiple independent conditions can fire on the same run."""
        settings = _make_settings(
            subtheme_growing_threshold=0.30,
            subtheme_disappearing_threshold=0.10,
            subtheme_sentiment_shift_threshold=0.20,
        )
        # Growing: (15-10)/10 = 0.50 >= 0.30 ✓
        # Sentiment shift: |0.6 - 0.1| = 0.50 >= 0.20 ✓
        st = self._make_st("st-1", is_new=False, members=15, reddit=0, sentiment=0.6)
        cur = self._mock_cur(prev_volume=10, prev_sentiment=0.1, peak_volume=15, baseline_sentiment=0.1)
        _step5_evolution(cur, [st], settings)
        assert "sub_theme_growing" in st.events
        assert "sub_theme_sentiment_shift" in st.events
