class PipelineError(Exception):
    """Base exception for the pipeline module."""
    pass

class DuplicateArticleError(PipelineError):
    """Raised when an article is dropped due to deduplication (Stage 1)."""
    pass

class NoTopicMatchError(PipelineError):
    """Raised when an article matches no tracked topics (Stage 2)."""
    pass

class LLMServiceError(PipelineError):
    """Raised when the summarisation service fails (e.g. API timeout)."""
    pass

class DatabaseConnectionError(PipelineError):
    """Raised when database interactions fail."""
    pass
