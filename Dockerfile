# ─────────────────────────────────────────────────────────────────
# MULTI-STAGE BUILD
#
# One image used to serve every container, and it carried PyTorch — so the
# API gateway pulled ~2GB of it to serve JSON. The
# stages below let each service install only what it imports.
#
#   runtime-slim   base deps only          backend, alert-consumer, migrate
#   runtime-ml     + numpy/UMAP/HDBSCAN    pipeline-consumer, every celery process
#   runtime-heavy  + PyTorch + model       embedding-service only
#
# No Celery process can use runtime-slim, beat included: Celery imports every
# module in the app's `include` list at startup, and one of them pulls in
# numpy/umap/hdbscan.
#
# Build a specific one with:  docker build --target runtime-slim .
# docker-compose.yml selects the target per service.
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# BASE — shared interpreter and env for every stage.
# PYTHONUNBUFFERED forces Python to flush stdout/stderr immediately instead of
# buffering. Without it log output may not appear until the buffer fills, which
# makes debugging in Docker painful.
# ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONPATH=/app
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip


# ─────────────────────────────────────────────────────────────────
# RUNTIME-SLIM — no compiler, no ML.
# Everything in base.txt ships prebuilt wheels for aarch64, so this stage
# never needs build-essential and stays small.
# ─────────────────────────────────────────────────────────────────
FROM base AS runtime-slim
COPY requirements/base.txt requirements/base.txt
RUN pip install --no-cache-dir -r requirements/base.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"

CMD ["./docker-entrypoint.sh"]


# ─────────────────────────────────────────────────────────────────
# RUNTIME-ML — adds the clustering/numerics stack. Still no PyTorch.
#
# build-essential is required here and only here: hdbscan and the numba/llvmlite
# chain ship no aarch64 wheels and must compile from source on ARM hosts like
# the Oracle Ampere VM. The toolchain is purged in the same layer so it does not
# end up in the final image.
# ─────────────────────────────────────────────────────────────────
FROM base AS runtime-ml
COPY requirements/base.txt requirements/base.txt
COPY requirements/ml.txt requirements/ml.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir -r requirements/ml.txt \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh


# ─────────────────────────────────────────────────────────────────
# RUNTIME-HEAVY — the embedding service. The only image with PyTorch.
#
# torch is installed from the CPU wheel index so the build does not pull ~2GB
# of CUDA. It is pinned for the same reason as the clustering block in
# requirements/ml.txt: torch produces the embeddings everything else is derived
# from, and this pipeline is sensitive enough that a version bump can reshape
# clustering.
# ─────────────────────────────────────────────────────────────────
FROM base AS runtime-heavy
COPY requirements/base.txt requirements/base.txt
COPY requirements/ml.txt requirements/ml.txt
COPY requirements/heavy.txt requirements/heavy.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.13.0 \
    && pip install --no-cache-dir -r requirements/heavy.txt \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Pre-download the Sentence-BERT model into the image at build time.
# app/adapters/ai/embedder.py forces HF_HUB_OFFLINE=1 at runtime — it refuses
# all network calls and reads only from the local cache. If the model is not
# already cached it crashes, which is the intended failure mode. Downloading
# here guarantees it is present offline. Adds ~420MB, removes the cold start.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-mpnet-base-v2')"

COPY app ./app

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "app.embedding_service:app", "--host", "0.0.0.0", "--port", "8001"]
