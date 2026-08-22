"""Errors raised by the AI adapters.

Kept in the adapter package rather than app/pipeline/exceptions.py on purpose.
Everything in that module subclasses PipelineError, and the orchestrator keys
its handling off that hierarchy — moving this there would silently change which
branch catches an embedding failure. It is also caught by the API layer
(app/services/topics.py), which has no business importing pipeline exceptions.
"""

from __future__ import annotations


class EmbeddingGenerationError(Exception):
    """Raised when embedding generation fails, locally or remotely."""
