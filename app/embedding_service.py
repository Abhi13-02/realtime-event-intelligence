"""Standalone embedding service — the only process that loads PyTorch.

Runs as its own container so the Sentence-BERT weights are resident exactly
once instead of once per process that needs a vector.

Deliberately NOT HuggingFace TEI. TEI is a different inference engine (Rust
/Candle, frequently fp16) and would not reproduce the vectors already stored in
pgvector bit-for-bit. This pipeline is documented as chaotically sensitive to
that: a 1.5e-08 perturbation once flipped a benchmark topic from 7 clusters at
100% recall to 2 at 25% (docs/discovery-accuracy-log.md v3). Running the exact
pinned torch/sentence-transformers stack from requirements.txt is the whole
point of this container.
"""

from __future__ import annotations

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.adapters.ai.base import EmbeddingGenerationError
from app.adapters.ai.embedder import MODEL_NAME, get_local_embedder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmbedRequest(BaseModel):
    inputs: list[str] = Field(..., min_length=1)


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Load the model at boot, not on first request.

    Without this the first topic anyone creates pays the several-second model
    load, and the caller's read timeout is what decides whether that is
    survivable. Loading here means the container is either ready or it is not.
    """
    get_local_embedder()
    logger.info("Embedding service ready — model %s loaded.", MODEL_NAME)
    yield


app = FastAPI(title="Embedding Service", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/embed", response_model=EmbedResponse)
def embed(request: EmbedRequest) -> EmbedResponse:
    """
    Encode one or more texts.

    Note this is a `def`, not an `async def`. FastAPI runs sync handlers in its
    threadpool, so a long mpnet forward pass cannot block the event loop and
    stall the health check. Making this async would serialise every request
    onto the loop thread.
    """
    try:
        vectors = get_local_embedder().encode_batch(request.inputs)
    except EmbeddingGenerationError as exc:
        # 503 rather than 500: the caller's retry logic should treat this as a
        # transient service problem, which is what it is.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return EmbedResponse(embeddings=vectors)
