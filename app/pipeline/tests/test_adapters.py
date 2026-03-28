import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.pipeline.adapters.db_adapter import PostgresAdapter
from app.pipeline.adapters.llm_adapter import GeminiAdapter
from app.pipeline.adapters.bus_adapter import MockKafkaAdapter
from app.pipeline.exceptions import LLMServiceError

@patch('app.pipeline.adapters.db_adapter.psycopg2.connect')
def test_db_adapter_check_url(mock_connect):
    mock_conn = MagicMock()
    mock_connect.return_value = mock_conn
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    
    # Simulate URL exists
    mock_cursor.fetchone.return_value = [1]
    
    adapter = PostgresAdapter("fake_conn_string")
    assert adapter.check_url_exists("http://example.com") == True
    mock_cursor.execute.assert_called_with("SELECT 1 FROM articles WHERE url = %s LIMIT 1", ("http://example.com",))

@patch('app.pipeline.adapters.llm_adapter.genai.GenerativeModel')
def test_gemini_adapter_success(mock_model):
    mock_instance = MagicMock()
    mock_model.return_value = mock_instance
    mock_instance.generate_content.return_value.text = "Mocked Summary"
    
    adapter = GeminiAdapter("fake_api_key")
    summary = adapter.generate_summary("Headline", "Content")
    
    assert summary == "Mocked Summary"
    mock_instance.generate_content.assert_called_once()

@patch('app.pipeline.adapters.llm_adapter.genai.GenerativeModel')
def test_gemini_adapter_failure(mock_model):
    mock_instance = MagicMock()
    mock_model.return_value = mock_instance
    mock_instance.generate_content.side_effect = Exception("API Error")
    
    adapter = GeminiAdapter("fake_api_key")
    with pytest.raises(LLMServiceError, match="Gemini API error"):
        adapter.generate_summary("Headline", "Content")

def test_mock_bus_adapter(capsys):
    adapter = MockKafkaAdapter()
    adapter.publish_matched_article(uuid4(), uuid4(), 0.95, [uuid4(), uuid4()])
    
    captured = capsys.readouterr()
    assert "[EVENT BUS]" in captured.out
