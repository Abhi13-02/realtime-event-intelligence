class PipelineError(Exception):
    """Base exception for the pipeline module."""
    pass

class DuplicateArticleError(PipelineError):
    """Raised when an article is dropped during URL or vector deduplication."""
    pass

class NoTopicMatchError(PipelineError):
    """Raised when an article matches no tracked topics after deduplication."""
    pass

class LLMServiceError(PipelineError):
    """Raised when the summarisation service fails (e.g. API timeout)."""
    pass

class DatabaseConnectionError(PipelineError):
    """Raised when database interactions fail."""
    pass
