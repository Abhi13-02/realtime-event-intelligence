import pytest
from unittest.mock import MagicMock
from uuid import uuid4
from pydantic import HttpUrl

from app.pipeline.models import RawArticle, Topic, ProcessedArticle, ScoredMatch
from app.pipeline.exceptions import DuplicateArticleError, NoTopicMatchError, PipelineError
from app.pipeline.orchestrator import ArticlePipeline

@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    # Mock embedding return
    embedder.encode_text.return_value = [0.1] * 384
    return embedder

@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.generate_summary.return_value = "This is a test summary."
    return llm

@pytest.fixture
def mock_bus():
    return MagicMock()

@pytest.fixture
def pipeline(mock_db, mock_embedder, mock_llm, mock_bus):
    pipeline = ArticlePipeline(mock_db, mock_embedder, mock_llm, mock_bus, max_retries=1)
    
    # Setup some test topics
    topic1 = Topic(id=uuid4(), name="Tech", threshold=0.6, embedding=[0.1] * 384)
    topic2 = Topic(id=uuid4(), name="Sports", threshold=0.8, embedding=[-0.1] * 384)
    pipeline.refresh_topic_cache([topic1, topic2])
    
    return pipeline

@pytest.fixture
def raw_article():
    return RawArticle(
        url="http://example.com/tech-news",
        headline="Tech News",
        content="<p>Some clean content here about technology.</p>",
        source_id=uuid4()
    )

def test_pipeline_happy_path(pipeline, raw_article, mock_db, mock_embedder, mock_llm, mock_bus):
    # Setup happy path mocks
    mock_db.check_url_exists.return_value = False
    mock_db.vector_search_duplicate.return_value = False
    mock_db.get_source_credibility.return_value = 0.9
    
    article_id = uuid4()
    mock_db.store_article_and_matches.return_value = article_id
    
    # Mock user matching the threshold
    user_id = uuid4()
    mock_db.get_users_meeting_threshold.return_value = [user_id]

    pipeline.process_article(raw_article)

    # Asserts
    mock_db.check_url_exists.assert_called_once()
    mock_embedder.encode_text.assert_called_once()
    mock_db.vector_search_duplicate.assert_called_once()
    mock_db.store_article_and_matches.assert_called_once()
    mock_llm.generate_summary.assert_called_once()
    mock_db.update_article_summary.assert_called_once()
    
    # Event bus should be called matching Topic 1 (Tech) which has identical embeddings (cosine = 1.0)
    assert mock_bus.publish_matched_article.call_count == 1
    call_args = mock_bus.publish_matched_article.call_args[1]
    assert call_args["article_id"] == article_id
    assert call_args["user_ids"] == [user_id]


def test_pipeline_drops_duplicate_url(pipeline, raw_article, mock_db):
    mock_db.check_url_exists.return_value = True
    
    # Process should return safely and log, not raise
    pipeline.process_article(raw_article)
    
    mock_db.check_url_exists.assert_called_once()
    # It drops early, so these should not be called
    mock_db.vector_search_duplicate.assert_not_called()
    mock_db.store_article_and_matches.assert_not_called()

def test_pipeline_drops_no_topic_match(pipeline, raw_article, mock_db, mock_embedder):
    mock_db.check_url_exists.return_value = False
    mock_db.vector_search_duplicate.return_value = False
    
    # Return an embedding orthogonal to topic embeddings, resulting in 0 similarity (< 0.65 threshold)
    # The dot product of [0.0]*384 and [0.1]*384 is 0.0
    mock_embedder.encode_text.return_value = [0.0] * 384
    
    pipeline.process_article(raw_article)
    
    # Should drop
    mock_db.store_article_and_matches.assert_not_called()

def test_pipeline_gemini_retries_and_fails(pipeline, raw_article, mock_db, mock_llm):
    mock_db.check_url_exists.return_value = False
    mock_db.vector_search_duplicate.return_value = False
    mock_db.store_article_and_matches.return_value = uuid4()
    
    # Make LLM fail every time
    mock_llm.generate_summary.side_effect = Exception("API down")
    
    with pytest.raises(PipelineError, match="Stage 5 permanent failure"):
        pipeline.process_article(raw_article)
        
    # Max retries = 1, so it should be called 2 times (initial + 1 retry)
    assert mock_llm.generate_summary.call_count == 2
