"""HTTP client for the dedicated embedding-service container.

This is the only embedding path used at runtime by the API, the pipeline and
the Celery workers. None of them import app/adapters/ai/embedder.py any more,
which is what keeps PyTorch out of their images entirely — the import is the
thing that costs 1.5GB, not the call.

Transport is pooled HTTP/1.1, not gRPC. The payload is a handful of short
strings in and 768 floats out; what costs milliseconds here is the mpnet
forward pass, not serialisation. gRPC would add a protobuf toolchain to CI and
remove the ability to debug with curl, in exchange for saving a rounding
error. The one optimisation that does matter is connection reuse, which is why
the client objects are built once and held for the process lifetime rather
than being opened per call.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import List

import httpx

from app.adapters.ai.base import EmbeddingGenerationError, EmbeddingInterface
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Connect fast, then wait. A refused connection means the service is down and
# should fail quickly; a slow response means mpnet is working through a batch
# on a 2-vCPU box, which legitimately takes seconds.
_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
_LIMITS = httpx.Limits(max_keepalive_connections=10, max_connections=20)

# Embedding is a pure function of its input, so retrying can never double-apply
# anything. Retries cover broker-style blips: the service restarting, or a
# connection reaped mid-flight.
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 0.5


class EmbeddingClient(EmbeddingInterface):
    """Calls the embedding-service. Sync methods for workers, async for FastAPI."""

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or get_settings().embedding_service_url).rstrip("/")
        self._endpoint = f"{self._base_url}/embed"
        self._client = httpx.Client(timeout=_TIMEOUT, limits=_LIMITS)
        self._aclient: httpx.AsyncClient | None = None

    # ── sync (pipeline consumer, Celery workers) ─────────────────────────

    def encode_text(self, text: str) -> List[float]:
        return self.encode_batch([text])[0]

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._client.post(self._endpoint, json={"inputs": texts})
                response.raise_for_status()
                return _parse(response.json(), expected=len(texts))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS:
                    logger.warning(
                        "Embedding request failed (attempt %d/%d): %s",
                        attempt, _MAX_ATTEMPTS, exc,
                    )
                    time.sleep(_BACKOFF_SECONDS * attempt)

        raise EmbeddingGenerationError(
            f"Embedding service unreachable after {_MAX_ATTEMPTS} attempts: {last_exc}"
        ) from last_exc

    # ── async (FastAPI request handlers) ─────────────────────────────────

    def _get_aclient(self) -> httpx.AsyncClient:
        # Built lazily: an AsyncClient binds to the running event loop, so it
        # cannot be created at import time in a worker that has no loop.
        if self._aclient is None:
            self._aclient = httpx.AsyncClient(timeout=_TIMEOUT, limits=_LIMITS)
        return self._aclient

    async def aencode_text(self, text: str) -> List[float]:
        return (await self.aencode_batch([text]))[0]

    async def aencode_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        import asyncio

        client = self._get_aclient()
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await client.post(self._endpoint, json={"inputs": texts})
                response.raise_for_status()
                return _parse(response.json(), expected=len(texts))
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS:
                    logger.warning(
                        "Embedding request failed (attempt %d/%d): %s",
                        attempt, _MAX_ATTEMPTS, exc,
                    )
                    await asyncio.sleep(_BACKOFF_SECONDS * attempt)

        raise EmbeddingGenerationError(
            f"Embedding service unreachable after {_MAX_ATTEMPTS} attempts: {last_exc}"
        ) from last_exc

    async def aclose(self) -> None:
        if self._aclient is not None:
            await self._aclient.aclose()
            self._aclient = None


def _parse(payload: dict, *, expected: int) -> List[List[float]]:
    """Validate the service response rather than blind-indexing it."""
    embeddings = payload["embeddings"]
    if len(embeddings) != expected:
        raise ValueError(
            f"Embedding service returned {len(embeddings)} vectors for {expected} inputs"
        )
    return embeddings


@lru_cache
def get_embedding_client() -> EmbeddingClient:
    """Return the process-wide embedding client, sharing one connection pool."""
    return EmbeddingClient()
