# RealTime Event Intelligence

A production-grade, multi-tenant, event-driven intelligence platform that continuously ingests global news sources (RSS feeds, Reddit, Hacker News), processes every article through an **8-stage fail-fast NLP pipeline**, performs automated **sub-theme narrative discovery & clustering (UMAP + HDBSCAN + LLM)**, and delivers instantaneous, personalized topic alerts over **WebSockets** via a **Redis Pub/Sub backplane**.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Key Features](#key-features)
- [Architecture & Data Flow](#architecture--data-flow)
- [Core Engineering Deep Dives](#core-engineering-deep-dives)
  - [1. The PostgreSQL SKIP LOCKED Work Queue (Replacing Kafka)](#1-the-postgresql-skip-locked-work-queue-replacing-kafka)
  - [2. The 8-Stage Fail-Fast NLP Pipeline](#2-the-8-stage-fail-fast-nlp-pipeline)
  - [3. Sub-Theme & Narrative Discovery Engine](#3-sub-theme--narrative-discovery-engine)
  - [4. Dedicated Embedding Microservice](#4-dedicated-embedding-microservice)
  - [5. Horizontally Scalable WebSockets & Ticket Auth](#5-horizontally-scalable-websockets--ticket-auth)
- [Container Topology & Service Inventory](#container-topology--service-inventory)
- [Database Schema & Vector Search](#database-schema--vector-search)
- [API Reference](#api-reference)
- [Local Development Setup](#local-development-setup)
- [Production Deployment & CI/CD](#production-deployment--cicd)
  - [Zero Open Inbound Ports (Cloudflare Tunnel)](#zero-open-inbound-ports-cloudflare-tunnel)
  - [GitHub Actions CI/CD Pipeline](#github-actions-cicd-pipeline)
  - [Operator Cheat-Sheet](#operator-cheat-sheet)
- [Production Trade-offs & Engineering Decisions](#production-trade-offs--engineering-decisions)

---

## System Architecture

```
                                  [EXTERNAL SOURCES]
                  RSS Feeds (BBC, Reuters...) │ Hacker News │ Reddit
                                              │
                                              ▼
                                   [CELERY INGESTION WORKERS]
                              Scheduled periodically by Celery Beat
                                              │
                                              ▼ (Batch INSERT)
                      ┌────────────────────────────────────────────────┐
                      │          POSTGRESQL WORK QUEUE                 │
                      │   queue_messages ('raw-articles', status='pending')   │
                      └───────────────────────┬────────────────────────┘
                                              │
                                              ▼ (SELECT ... FOR UPDATE SKIP LOCKED)
                                   [PIPELINE CONSUMER]
                      ┌────────────────────────────────────────────────┐
                      │ 8-STAGE FAIL-FAST NLP PIPELINE                 │
                      │ Stage 0: URL Deduplication (Indexed B-Tree)    │
                      │ Stage 1: Text Preprocessing & Embedding        ├────▶ [EMBEDDING SERVICE]
                      │ Stage 2: Vector Deduplication (pgvector 0.95)  │      (Sentence-BERT 768d)
                      │ Stage 3: In-Memory Matrix Topic Match          │
                      │ Stage 4: Relevance & Credibility Scoring       │
                      │ Stage 5: Article & Match Persistence           │
                      │ Stage 6: Summarisation (Feed / Groq LLM)       │
                      │ Stage 7: Route to 'matched-articles' Queue     │
                      └───────────────────────┬────────────────────────┘
                                              │
                                              ▼ (INSERT 'matched-articles')
                      ┌────────────────────────────────────────────────┐
                      │             ALERT CONSUMER                     │
                      │  - Writes durable rows to 'alerts' table       │
                      │  - Publishes to Redis Pub/Sub: alerts:broadcast│
                      └───────────────────────┬────────────────────────┘
                                              │
                       Redis Pub/Sub Channel: alerts:broadcast
                                              │
                  ┌───────────────────────────┴───────────────────────────┐
                  ▼                                                       ▼
        [BACKEND REPLICA 1]                                     [BACKEND REPLICA 2]
     FastAPI REST + WebSocket                                FastAPI REST + WebSocket
                  │                                                       │
                  └───────────────────────────┬───────────────────────────┘
                                              │ (WSS push with single-use tickets)
                                              ▼
                                   [NEXT.JS 16 WEB CLIENT]
                                   Real-time toast notifications,
                                   Topic Dashboard, Narrative Graphs
```

---

## Key Features

- **Multi-Tenant Personalized Topic Intelligence:** Users define custom topics and subtopics with adjustable sensitivity levels (`broad`, `balanced`, `high`).
- **Multi-Source Autonomous Crawlers:** Distributed Celery workers continuously pull from major global RSS feeds, the Hacker News Firebase REST API, and Reddit subreddits.
- **Fail-Fast 8-Stage NLP Pipeline:** Designed with cheapest filters first (URL check) before invoking heavy matrix and vector operations.
- **768-Dimensional Semantic Vector Search:** Powered by `sentence-transformers/all-mpnet-base-v2` and PostgreSQL `pgvector` with HNSW cosine indexing.
- **Unsupervised Narrative Discovery (Sub-themes):** Uses **UMAP** dimensionality reduction (768d $\to$ 10d) and **HDBSCAN** clustering on rolling windows to detect organic news narrative clusters.
- **Social Signal & Sentiment Mapping:** Correlates Reddit discussions against news cluster centroids and analyzes public sentiment via **VADER**.
- **LLM-Powered Narrative Synthesis:** Calls **Groq** (`llama-3.3-70b-versatile`) with prompt guardrails to generate human-readable titles, narrative summaries, and relevance checks.
- **Cluster State Machine:** Automatically tracks narrative lifecycles across 6 states (`new`, `growing`, `steady`, `declining`, `dormant`, `revival`) and emits intelligence alerts on surges.
- **Scalable Real-Time WebSocket Alerts:** In-app real-time notification push powered by a Redis Pub/Sub backplane and authenticated via single-use tickets.
- **Zero-Inbound-Port Edge Security:** Edge ingress handled entirely by an outbound Cloudflare Tunnel into an internal nginx reverse proxy.

---

## Architecture & Data Flow

### The Lifecycle of an Ingested Article

1. **Scheduled Ingestion:** Celery Beat schedules source tasks (`fetch_rss`, `fetch_reddit`, `fetch_hacker_news`) to Celery workers.
2. **Batch Queue Insertion:** The worker extracts article metadata and writes records to the `queue_messages` table under `queue = 'raw-articles'` with `status = 'pending'`.
3. **Competing Consumer Claim:** The `pipeline-consumer` claims a batch of messages using `SELECT ... FOR UPDATE SKIP LOCKED` and transitions them to `status = 'processing'`.
4. **NLP Processing:** The article passes sequentially through the 8 stages:
   - If the URL is already recorded, Stage 0 drops it immediately.
   - Text is normalized and sent over HTTP to the dedicated `embedding-service` container for Sentence-BERT vector generation.
   - Near-identical syndicated articles are dropped at Stage 2 if pgvector cosine similarity $\ge 0.95$.
   - The vector is evaluated against an in-memory cached matrix of user topics at Stage 3.
   - Matched articles are saved to PostgreSQL at Stage 5. Reddit posts exit early after Stage 5 to be clustered later.
   - Matched news articles are published to the `matched-articles` queue.
5. **Alert Fan-out:** The `alert-consumer` claims from `matched-articles`, commits alert rows to the database (`status = 'pending'`), and broadcasts the payload to Redis Pub/Sub (`alerts:broadcast`).
6. **WebSocket Delivery:** The FastAPI gateway replica holding the connected user's WebSocket receives the Redis broadcast and pushes a live JSON payload to the user's browser. If disconnected, the user pulls unread alerts on reconnect via `GET /v1/alerts`.

---

## Core Engineering Deep Dives

### 1. The PostgreSQL SKIP LOCKED Work Queue (Replacing Kafka)

The message transport was originally implemented using Apache Kafka (KRaft mode). It was intentionally migrated to a PostgreSQL table (`queue_messages`) using `SELECT ... FOR UPDATE SKIP LOCKED`.

#### Why Kafka Was Replaced
| Metric | Real Production Metric | Kafka Overhead |
|---|---|---|
| Ingestion Rate | ~0.15 to 5 msgs/sec | Broker built for $10^5$–$10^6$ msgs/sec |
| Consumer Throughput | ~1 article/sec per worker (embedding-bound) | Consumer slower than queue; queue rarely backs up |
| Memory Footprint | Minimal SQL table | Single-broker JVM held **1.2–1.5 GB RAM** on a 12 GB ARM VM |
| Horizontal Scaling | Unlimited competing consumers | Strictly capped at **3 workers** (Kafka partition count) |

#### How the Claim Works
```sql
SELECT id, payload FROM queue_messages
WHERE queue = %s AND status = 'pending'
ORDER BY id
FOR UPDATE SKIP LOCKED
LIMIT %s;
```
- `FOR UPDATE` locks selected rows for the transaction.
- `SKIP LOCKED` instructs concurrent workers to skip locked rows and claim the next available batch without waiting.
- **Short-Transaction Trade-off:** The transaction commits immediately upon flipping the state to `'processing'`, releasing DB row locks while the worker performs CPU-heavy NLP tasks.

```
                 ┌──────────────────────────────┐
                 ↓                              │
publish() → pending → claim() → processing → ack() → done
                 ↑                    │
                 │                    ├─ retry()  (attempts < max) ──┘
                 │                    │
                 └── reap_stalled() ──┤  (worker died, timeout passed)
                                      │
                                      └─ retry() at max, or fail() → failed
```

#### Crash Recovery & Dead-Letter Queue
- **Reaper (`reap_stalled()`):** If a worker container crashes mid-processing, the row remains in `'processing'`. A periodic reaper sweeps rows where `locked_at` is older than the visibility timeout (default: 300 seconds) and returns them to `'pending'`.
- **Dead-Letter State (`failed`):** If a poison message repeatedly crashes workers, `retry()` increments `attempts`. Once `attempts >= 5`, the row is parked in `'failed'` with `last_error` recorded, avoiding partition blockage.

---

### 2. The 8-Stage Fail-Fast NLP Pipeline

Implemented in [`app/pipeline/orchestrator.py`](file:///c:/Users/Abhinav%20Dev/OneDrive/Desktop/Projects/ALL%20Projects/SeriousProjects/realtime-topic-tracking/realtime-topic-intelligence/app/pipeline/orchestrator.py) and [`stages.py`](file:///c:/Users/Abhinav%20Dev/OneDrive/Desktop/Projects/ALL%20Projects/SeriousProjects/realtime-topic-tracking/realtime-topic-intelligence/app/pipeline/stages.py).

| Stage | Operation | Mechanism | Resource Cost |
|---|---|---|---|
| **0** | **URL Deduplication** | Indexed B-tree lookup on `articles.url` | Negligible ($\sim 0.5$ ms) |
| **1** | **Text Preprocess & Embed** | HTML strip, 2000-char truncation, Sentence-BERT forward-pass | Heavy ($\sim 25$ ms) |
| **2** | **Vector Deduplication** | `pgvector` HNSW cosine distance search ($\ge 0.95$) | Medium ($\sim 5$ ms) |
| **3** | **Topic Matching** | In-memory cached matrix multiplication ($M_{\text{topic}} \cdot v_{\text{article}}$) | Low ($\sim 2$ ms) |
| **4** | **Relevance Scoring** | Weighted combination of cosine similarity + source credibility | Negligible |
| **5** | **Store Article & Matches** | SQL insert into `articles` and `article_topic_matches` | DB write |
| **6** | **Summarisation** | Clean description bypass (`use_description=True`) / Groq LLM | Bypassed / API call |
| **7** | **Publish Match** | Insert matching article into `'matched-articles'` queue | DB write |

#### Key Pipeline Optimizations
- **Ordering is Key:** Stage 0 eliminates ~90% of duplicate crawler hits before spending a single CPU cycle on tensor embedding.
- **Matrix Topic Matching in Memory:** Rather than running SQL vector queries per topic per user, all active topics are cached in memory (refreshed every 300 seconds). Stage 3 runs a single vectorized matrix dot product across all active topics simultaneously:
  $$\text{similarity} = \frac{M_{\text{topics}} \cdot v_{\text{article}}}{\|M_{\text{topics}}\| \cdot \|v_{\text{article}}\|}$$
- **Persistence of Dropped Articles:** Articles rejected at Stage 2 or 3 are saved with `status = 'dropped'`. Since their embedding has already been computed, Stage 0 catches their URL on future crawls (no redundant re-embedding), and when a user creates a new topic, historical dropped vectors can be backfilled instantly.
- **Reddit Early Exit:** Reddit posts exit after Stage 5. They do not trigger real-time article alerts; instead, they are stored to provide social signal during narrative clustering.

---

### 3. Sub-Theme & Narrative Discovery Engine

Implemented in [`app/tasks/discovery/subtheme_discovery.py`](file:///c:/Users/Abhinav%20Dev/OneDrive/Desktop/Projects/ALL%20Projects/SeriousProjects/realtime-topic-tracking/realtime-topic-intelligence/app/tasks/discovery/subtheme_discovery.py).

```
[News Article Vectors] ──▶ [UMAP: 768d -> 10d] ──▶ [HDBSCAN Clustering] ──▶ News Clusters
                                                                                   │
[Reddit Post Vectors] ────▶ [Anchor Cosine Proximity Matching] ───────────────────┤
                                                                                   ▼
[Reddit Comments] ────────▶ [Async VADER Sentiment Analysis] ─────────────────────┤
                                                                                   ▼
[User Topic Spec] ────────▶ [Groq LLM: Relevance Filter + Naming + Synthesis] ───┤
                                                                                   ▼
[Previous State] ─────────▶ [State Machine Evolution: Delta Transition] ─────────┤
                                                                                   ▼
                                                             [Publish Sub-Theme Alerts]
```

1. **UMAP Dimensionality Reduction:** 768-dimensional embeddings suffer from metric dispersion in high dimensions. UMAP with cosine metric reduces them to 10 dimensions while preserving local and global manifold structure.
2. **HDBSCAN Clustering:** Hierarchical density-based clustering groups articles into natural narrative threads without requiring an arbitrary $k$ parameter. Points not belonging to a dense cluster are safely designated as noise (`-1`).
3. **Centroid & 3-Anchor Representation:** For each cluster, the mean vector is the **Centroid**, and the 3 closest articles are designated as **Anchors**.
4. **Social Signal Alignment:** Reddit posts are assigned to a news cluster based on the maximum cosine similarity across the cluster's centroid and its 3 anchors.
5. **VADER Sentiment Analysis:** Async scrapers pull Reddit community comments for assigned posts, calculating positive, neutral, and negative compound sentiment scores.
6. **Groq LLM Synthesis with Token Budgeting:** Sample headlines (capped at 10 headlines, 100 chars each) and topic instructions are sent to Groq (`llama-3.3-70b-versatile`) to generate a concise title and narrative summary. A sensitivity gate rejects off-topic clusters before they reach the user.
7. **Cluster State Evolution:** Clusters are tracked across discovery runs:
   - `new`: newly formed cluster meeting minimum size threshold.
   - `growing`: volume increased significantly over the previous run.
   - `steady`: stable volume.
   - `declining`: volume decreasing run-over-run.
   - `dormant`: no recent articles.
   - `revival`: an old dormant cluster reignited with new coverage.
   - Emits transition events (`sub_theme_emerging`, `sub_theme_growing`, etc.) to the alert stream.

---

### 4. Dedicated Embedding Microservice

Implemented in [`app/embedding_service.py`](file:///c:/Users/Abhinav%20Dev/OneDrive/Desktop/Projects/ALL%20Projects/SeriousProjects/realtime-topic-tracking/realtime-topic-intelligence/app/embedding_service.py).

- **Isolated PyTorch Memory:** Sentence-BERT model weights (~420 MB) are loaded **once** in the `embedding-service` container, rather than duplicated across FastAPI, Celery workers, and pipeline consumer containers.
- **Deterministic Embeddings:** Explicitly uses pinned PyTorch and `sentence-transformers` rather than HuggingFace Text Embeddings Inference (TEI). TEI's fp16 Candle/Rust inference causes minor floating-point divergence, which can unpredictably split or shift HDBSCAN clusters.
- **Threadpool Concurrency:** The `/embed` endpoint is declared as `def embed(...)` instead of `async def`. FastAPI automatically executes synchronous handlers in a background threadpool, ensuring CPU-bound matrix forward passes do not block the asynchronous event loop.

---

### 5. Horizontally Scalable WebSockets & Ticket Auth

Implemented in [`app/alert/websocket.py`](file:///c:/Users/Abhinav%20Dev/OneDrive/Desktop/Projects/ALL%20Projects/SeriousProjects/realtime-topic-tracking/realtime-topic-intelligence/app/alert/websocket.py) and [`app/adapters/redis_pubsub.py`](file:///c:/Users/Abhinav%20Dev/OneDrive/Desktop/Projects/ALL%20Projects/SeriousProjects/realtime-topic-tracking/realtime-topic-intelligence/app/adapters/redis_pubsub.py).

#### The Multi-Replica Problem
WebSockets maintain an in-memory TCP socket per connected client. If Backend Replica A holds User 1's socket, but Backend Replica B processes User 1's alert, Replica B cannot reach Replica A's memory.

#### The Solution: Redis Pub/Sub Backplane
1. When an alert triggers, the `alert-consumer` writes the persistent record to PostgreSQL (`alerts` table).
2. It publishes an event payload to Redis channel `alerts:broadcast`.
3. Every FastAPI gateway replica subscribes to `alerts:broadcast`.
4. If a replica has User 1's socket in its local connection manager, it serializes and pushes the message. Replicas without a matching socket simply ignore the message.
5. If the client is completely offline, the database row remains in `status = 'pending'`, and the frontend reconciles via `GET /v1/alerts` upon reconnection.

#### Single-Use Ticket Handshake
Because standard browser WebSocket APIs do not permit custom HTTP headers like `Authorization: Bearer <jwt>`, sending JWTs in URL query parameters (`/ws?token=...`) exposes them in server access logs and browser histories.
1. Frontend makes an authenticated POST request: `POST /v1/ws/ticket` with `Authorization: Bearer <JWT>`.
2. Backend generates a random UUID ticket, saves it in Redis `db=1` with a **30-second TTL**, mapped to `user_id`.
3. Frontend initiates WebSocket handshake: `wss://.../v1/ws?ticket=<uuid>`.
4. Backend atomically gets and deletes the ticket (`GETDEL`). If valid, the connection is accepted.

---

## Container Topology & Service Inventory

All containers build from a multi-stage [`Dockerfile`](file:///c:/Users/Abhinav%20Dev/OneDrive/Desktop/Projects/ALL%20Projects/SeriousProjects/realtime-topic-tracking/realtime-topic-intelligence/Dockerfile) sharing the same codebase, differentiated by command and target.

| Container | Image / Target | Role | Resources / Scaling |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:0.8.2-pg15` | Persistent store (articles, topics, vectors, queue) | Persistent volume `postgres_data` |
| `redis` | `redis:7.4.8-alpine` | Celery broker (`db=0`), WS tickets (`db=1`), Pub/Sub backplane | In-memory, ephemeral |
| `migrate` | `runtime-slim` | One-shot Alembic migration runner (`alembic upgrade head`) | Runs at boot, exits 0 |
| `embedding-service` | `runtime-heavy` | Hosts PyTorch & Sentence-BERT `all-mpnet-base-v2` | Single instance, exposes port 8001 |
| `backend` | `runtime-slim` | FastAPI REST API & WebSocket gateway | Horizontal scaling behind proxy |
| `celery-worker` | `runtime-ml` | Executes crawling and notification tasks | Horizontal scaling |
| `celery-worker-discovery` | `runtime-ml` | Dedicated prefork worker for CPU-heavy UMAP/HDBSCAN | Isolated queue (`discovery`) |
| `celery-beat` | `runtime-ml` | Periodic task scheduler (cron) | Singleton process |
| `pipeline-consumer` | `runtime-ml` | Drains `raw-articles` queue through 8-stage NLP pipeline | Horizontal scaling (`SKIP LOCKED`) |
| `alert-consumer` | `runtime-slim` | Claims alert queues, writes alert rows, publishes to Redis | Dual-stream async loop |
| `frontend` | `frontend/Dockerfile` | Next.js 16 App Router (standalone Node 22 build) | Deploy profile only |
| `proxy` | `nginx:alpine` | Single entrypoint: routes `/v1` to backend, `/` to frontend | Deploy profile only |
| `cloudflared` | `cloudflare/cloudflared` | Outbound tunnel to Cloudflare Edge | Deploy profile only |

---

## Database Schema & Vector Search

Defined via SQLAlchemy in [`app/db/models.py`](file:///c:/Users/Abhinav%20Dev/OneDrive/Desktop/Projects/ALL%20Projects/SeriousProjects/realtime-topic-tracking/realtime-topic-intelligence/app/db/models.py) and managed by 18 Alembic migrations.

### Core Tables

- **`users`**: Multi-tenant user accounts with email, password hash, and roles.
- **`topics`**: Monitored topics with `parent_embedding` (vector(768)), `subtopics` (JSONB list of subtopic strings and vectors), and sensitivity thresholds (`broad`, `balanced`, `high`).
- **`sources`**: Ingestion source configurations (RSS feeds, subreddits, HN) with credibility scores (0.0 to 1.0).
- **`articles`**: Stored news and social media items. Includes `url` (UNIQUE), `title`, `content`, `summary`, `status` (`passed`, `dropped`), and `embedding` (`vector(768)`).
- **`article_topic_matches`**: Junction table recording which articles matched which topics, their cosine similarity, and credibility-adjusted relevance score.
- **`alerts`**: User notification records with delivery status (`pending`, `delivered`, `read`).
- **`sub_themes`**: Discovered narrative clusters with `centroid` (`vector(768)`), `keywords`, `sentiment_score`, `article_count`, `velocity`, `status` (`new`, `growing`, `steady`, `declining`, `dormant`, `revival`), and LLM-generated narrative summary.
- **`queue_messages`**: High-performance message queue table backing all asynchronous pipeline communication.

### Vector Search Indexing
`articles.embedding` is indexed with an **HNSW (Hierarchical Navigable Small World)** cosine index:
```sql
CREATE INDEX idx_articles_embedding_hnsw
ON articles USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```
Cosine similarity queries utilize the pgvector operator `<=>`:
```sql
SELECT id, 1 - (embedding <=> :target_embedding) AS similarity
FROM articles
WHERE 1 - (embedding <=> :target_embedding) >= :threshold
ORDER BY embedding <=> :target_embedding
LIMIT 10;
```

---

## API Reference

The FastAPI backend exposes versioned endpoints under `/v1/`. Interactive OpenAPI docs are available at `/docs`.

### Authentication (`/v1/auth`)
- `POST /v1/auth/register` — Create user account.
- `POST /v1/auth/login` — Authenticate and receive JWT bearer token.
- `GET /v1/auth/me` — Retrieve current user profile.

### Topics (`/v1/topics`)
- `GET /v1/topics` — List active topics for the authenticated user.
- `POST /v1/topics` — Create topic with keywords/subtopics and sensitivity setting. Automatically computes and stores embeddings.
- `GET /v1/topics/{id}` — Get topic details.
- `PATCH /v1/topics/{id}` — Update topic parameters.
- `DELETE /v1/topics/{id}` — Archive or delete topic.

### Alerts (`/v1/alerts`)
- `GET /v1/alerts` — Fetch user alerts with filtering (`is_read`, `topic_id`, pagination).
- `PATCH /v1/alerts/{id}/read` — Mark alert as read.
- `POST /v1/alerts/mark-all-read` — Mark all alerts as read.

### Intelligence & Sub-Themes (`/v1/intelligence`)
- `GET /v1/intelligence/{topic_id}/subthemes` — List discovered sub-themes, narrative summaries, and state evolution for a topic.
- `GET /v1/intelligence/subthemes/{id}/articles` — Retrieve member articles belonging to a narrative cluster.
- `POST /v1/intelligence/discover/{topic_id}` — Manually trigger an out-of-band discovery clustering run.

### Real-Time WebSocket (`/v1/ws`)
- `POST /v1/ws/ticket` — Exchange a Bearer JWT for a single-use 30s connection ticket.
- `GET /v1/ws?ticket={uuid}` — Open long-lived WebSocket connection for live alert streaming.

### Admin Controls (`/v1/admin`)
- Dynamic tuning of pipeline thresholds, crawler polling intervals, discovery parameters, and system health statistics.

---

## Local Development Setup

### Prerequisites
- Docker and Docker Compose (v2.20+)
- Python 3.12+ (for local testing/tooling)
- Node.js 22+ (for frontend development)

### 1. Clone & Configure
```bash
git clone https://github.com/Abhi13-02/realtime-event-intelligence.git
cd realtime-event-intelligence
cp .env.example .env
```
Fill in the required environment variables in `.env` (Groq API Key, database passwords, etc.).

### 2. Run Backend & Pipeline Services
```bash
docker compose up --build
```
This starts:
- PostgreSQL 15 (`localhost:5432`) with pgvector pre-installed.
- Redis (`localhost:6379`).
- Migration container (runs `alembic upgrade head` and exits).
- Dedicated embedding service (`localhost:8001`).
- FastAPI backend (`localhost:8000`).
- Celery worker, discovery worker, and Celery beat.
- Pipeline consumer & alert consumer.

### 3. Run Frontend (Locally)
```bash
cd frontend
npm ci
npm run dev
```
Access the application at `http://localhost:3000`.

### 4. Running Integration Tests
Integration tests run against the live PostgreSQL queue implementation:
```bash
docker compose run --rm migrate pytest tests/test_pg_queue.py -v
```

---

## Production Deployment & CI/CD

The production environment is hosted on an **Oracle Cloud Infrastructure (OCI) ARM instance** running Ubuntu 22.04 (`aarch64`, 2 vCPU, 12 GB RAM) under a single Docker Compose stack.

### Zero Open Inbound Ports (Cloudflare Tunnel)

The virtual machine does **not expose port 80 or 443 to the public internet**.
- The `cloudflared` container dials **outward** to Cloudflare's global edge network and maintains persistent outbound tunnels.
- Inbound web traffic arrives via Cloudflare's edge through the established tunnel and is forwarded internally to the `proxy` container (`nginx:alpine`).
- nginx routes:
  - `/v1/*` $\to$ `backend:8000` (FastAPI REST & WebSocket upgrade)
  - `/*` $\to$ `frontend:3000` (Next.js server)
- Because both frontend and backend are served under the same origin, cross-origin request issues (CORS) are eliminated.

### GitHub Actions CI/CD Pipeline

The CI/CD workflow ([`.github/workflows/ci-cd.yml`](file:///c:/Users/Abhinav%20Dev/OneDrive/Desktop/Projects/ALL%20Projects/SeriousProjects/realtime-topic-tracking/realtime-topic-intelligence/.github/workflows/ci-cd.yml)) operates on every push to `main`:

```
   git push origin main
         │
         ▼
   ┌──────────────────────── GitHub Actions ────────────────────────┐
   │  backend-checks   (ruff lint + compileall syntax validation)   │
   │  frontend-checks  (eslint + full Next.js production build)     │
   │        │ (both must pass)                                      │
   │        ▼                                                       │
   │  deploy  ──SSH──▶  Oracle Cloud VM                             │
   └────────────────────────────────────────────────────────────────┘
                               │
                               ▼
             ┌──────────────── The VM (Ubuntu ARM) ─────────────────┐
             │  git fetch && git reset --hard origin/main           │
             │  docker compose up -d --build --remove-orphans       │
             │  docker compose restart proxy                        │
             │  docker image prune -f                               │
             │  health check (polls 8090/login and backend :8000)   │
             └──────────────────────────────────────────────────────┘
```

#### Why Nginx Is Restarted on Deploy (`restart proxy`)
Nginx resolves Docker internal service IPs (`backend`, `frontend`) once at startup. When containers are rebuilt, Docker assigns new internal IP addresses. Bouncing nginx forces a fresh internal DNS resolution, avoiding `502 Bad Gateway` errors.

### Operator Cheat-Sheet

Connect to the server:
```bash
ssh 24vm
```

Manage the stack:
```bash
cd ~/realtime-intel
C="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile deploy"

$C ps                                   # View container status & health
$C logs -f backend                      # Tail FastAPI backend logs
$C logs --tail 100 pipeline-consumer    # Check pipeline consumer throughput
$C logs --tail 100 alert-consumer       # Check alert dispatching
$C restart backend                      # Restart backend container
$C restart proxy                        # Refresh proxy DNS lookup
$C up -d --build --remove-orphans       # Run full manual production rebuild

# Inspect PostgreSQL directly
docker exec -it realtime-intel-postgres-1 psql -U $POSTGRES_USER -d $POSTGRES_DB
```

---

## Production Trade-offs & Engineering Decisions

1. **Single-Host Topology vs. Multi-Node Clusters:**
   The entire system runs on a single 12 GB ARM VM. This provides massive cost efficiency (free-tier infrastructure) while comfortably supporting hundreds of concurrent topics. While this introduces a single point of failure (SPOF), downtime during deploys is limited to ~5–10 seconds.
2. **PostgreSQL SKIP LOCKED vs. Distributed Message Brokers:**
   Trading Kafka for Postgres simplified the operational stack, reduced memory pressure by >1.2 GB, and eliminated partition-bound scaling limits. The trade-off is the loss of an immutable, infinitely rewindable log, which this workload does not require.
3. **In-Memory Topic Cache vs. Real-Time DB Lookups:**
   Evaluating incoming vectors against an in-memory NumPy matrix enables microsecond-level matching across hundreds of topics. The trade-off is that newly created user topics take up to 300 seconds (cache TTL) to begin matching live articles.
4. **Summary LLM Bypass:**
   Stage 6 summarisation is bypassed (`use_description=True`) because RSS feed descriptions are already clean and informative. Invoking an LLM per article before full-text web crawling is enabled would incur token costs with negligible user benefit.
5. **Disposable Redis State:**
   Redis holds the Celery task broker (`db=0`) and ephemeral WebSocket auth tickets (`db=1`). Because persistent application state lives exclusively in PostgreSQL with volume mounts, Redis data is safely disposable across restarts.

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
