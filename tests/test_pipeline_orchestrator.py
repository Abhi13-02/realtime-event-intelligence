from uuid import uuid4

from app.pipeline.orchestrator import ArticlePipeline
from app.pipeline.models import RawArticle


class _FakeDB:
    def __init__(self, *, url_exists: bool = False, vector_duplicate: bool = False):
        self.url_exists = url_exists
        self.vector_duplicate = vector_duplicate
        self.url_checks = 0
        self.vector_checks = 0

    def check_url_exists(self, url: str) -> bool:
        self.url_checks += 1
        return self.url_exists

    def vector_search_duplicate(self, embedding, threshold: float = 0.95) -> bool:
        self.vector_checks += 1
        return self.vector_duplicate

    def get_source_credibility(self, source_id):
        raise AssertionError("Should not reach relevance scoring in this test")

    def store_article_and_matches(self, article, matches):
        raise AssertionError("Should not store duplicates")

    def update_article_summary(self, article_id, summary: str) -> None:
        raise AssertionError("Should not summarise duplicates")

    def get_users_meeting_threshold(self, topic_id, relevance_score: float):
        raise AssertionError("Should not query users in this test")


class _FakeEmbedder:
    def __init__(self):
        self.calls = 0

    def encode_text(self, text: str):
        self.calls += 1
        return [0.1, 0.2, 0.3]


class _UnusedLLM:
    def generate_summary(self, headline: str, content: str) -> str:
        raise AssertionError("Should not summarise duplicates")


class _UnusedBus:
    def publish_matched_article(self, article_id, topic_id, relevance_score, user_id) -> None:
        raise AssertionError("Should not publish duplicates")


def _raw_article() -> RawArticle:
    return RawArticle(
        url="https://example.com/article",
        headline="Example headline",
        content="<p>Example content</p>",
        source_id=uuid4(),
    )


def test_url_duplicate_short_circuits_before_embedding() -> None:
    db = _FakeDB(url_exists=True)
    embedder = _FakeEmbedder()
    pipeline = ArticlePipeline(
        db=db,
        embedder=embedder,
        llm=_UnusedLLM(),
        bus=_UnusedBus(),
        thresholds={},
    )

    pipeline.process_article(_raw_article())

    assert db.url_checks == 1
    assert embedder.calls == 0
    assert db.vector_checks == 0


def test_vector_duplicate_runs_after_embedding() -> None:
    db = _FakeDB(vector_duplicate=True)
    embedder = _FakeEmbedder()
    pipeline = ArticlePipeline(
        db=db,
        embedder=embedder,
        llm=_UnusedLLM(),
        bus=_UnusedBus(),
        thresholds={},
    )

    pipeline.process_article(_raw_article())

    assert db.url_checks == 1
    assert embedder.calls == 1
    assert db.vector_checks == 1
