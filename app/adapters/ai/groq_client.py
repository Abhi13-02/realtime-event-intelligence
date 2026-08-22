"""Shared Groq client factory.

Groq was constructed in three separate places — the summariser, the topic
expander, and inline in the discovery task, which bypassed app/adapters/ai/
entirely. Each read the API key slightly differently: two from settings, one
straight from os.environ, so a missing key failed in two different ways
depending on which one you hit first.

One factory now owns construction and the key check. Callers that want a
different model still pass one; the model name itself continues to come from
settings.groq_model (GROQ_MODEL), which is what makes a provider decommission
an env change rather than an edit in three files.
"""

from __future__ import annotations

from functools import lru_cache

from groq import Groq

from app.core.config import get_settings


@lru_cache
def get_groq_client() -> Groq:
    """
    Process-wide Groq client.

    Cached because the SDK holds an HTTP connection pool; building one per task
    run throws that away. The client is thread-safe, which matters for the
    prefork Celery worker.
    """
    api_key = get_settings().groq_api_key
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set")
    return Groq(api_key=api_key)
