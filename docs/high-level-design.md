# High-Level Design — Real-Time Topic Tracking & Alert Intelligence System

> **Phase:** 2 — High-Level Design
> **Status:** Draft
> **Last Updated:** 2026-04-01
> **Depends on:** [requirements.md](./requirements.md)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Components](#2-components)
3. [Data Flow](#3-data-flow)
4. [Tech Stack Decisions](#4-tech-stack-decisions)
5. [Key Architectural Decisions](#5-key-architectural-decisions)
6. [Out of Scope for HLD](#6-out-of-scope-for-hld)

---

## 1. System Overview

The system is a multi-tenant, event-driven backend that continuously monitors a fixed set of sources, runs ingested content through a fail-fast NLP pipeline, and delivers personalised alerts to users via WebSocket, email, and SMS.

The core design principle is **separation of concerns across independent processes**:
- Ingestion does not know about users or topics
- Processing does not know about delivery channels
- Alerting does not know how content was sourced

Each layer communicates asynchronously through Kafka, making them independently scalable and independently deployable.

> 📝 **Engineering Note:** This is called an **event-driven architecture**. Components don't call each other directly — they emit events and consume events. This is the dominant pattern in large-scale backend systems (Uber, Netflix, LinkedIn all use it). It is also one of the most common system design interview topics at product companies.

---

## 2. Components

### 2.1 Ingestion Service
- Polls two sources on a schedule: GDELT and Reddit
- Runs as a Celery worker — independent of the FastAPI app process
- Publishes raw content directly to Kafka topic: `raw-articles`
- Has no knowledge of users or topics — it crawls broadly

**Two sources:**

| Source | Type | Content | Comments |
|--------|------|---------|----------|
| GDELT | News API | Structured news articles — headline, content, URL, publish date | No comments |
| Reddit | Social API | Posts from r/technology, r/worldnews, r/science, r/MachineLearning | Top 50 comments per post, included in the Kafka message |

RSS feeds (BBC, TechCrunch, Google News, Reuters) and Hacker News have been removed. GDELT provides broad, structured, continuously updated news coverage from thousands of outlets worldwide — it replaces the fixed RSS feed list entirely and at significantly higher coverage.

Reddit posts are **not** alert-generating content. They are crawled for two purposes: (1) their embeddings contribute to sub-theme volume counts and (2) their comments are the input to VADER sentiment analysis in the sub-theme discovery job. Reddit posts never appear in user alerts.

> 📝 **Engineering Note:** Ingestion is intentionally "dumb" — it just fetches and publishes. This is the **single responsibility principle**: one component, one job. It also means if Reddit's API changes, only the Reddit crawl task needs updating — nothing downstream is affected.

### 2.2 Celery + Redis (Scheduler)
- Celery is a distributed task queue — it manages scheduled and async jobs
- Redis acts as the message broker between FastAPI and Celery workers
- Triggers the ingestion service every 10 minutes per source
- Runs independently — if the FastAPI app crashes, polling continues

> 📝 **Engineering Note:** Why not just use a cron job? Cron is fine for simple scripts but doesn't handle retries, failure logging, distributed workers, or dynamic scheduling. Celery gives you all of that. This is the production-grade choice for any Python backend with background jobs.

### 2.3 Kafka
- Central message bus connecting all pipeline stages
- Three topics:
  - `raw-articles` — raw content published by ingestion service (GDELT articles + Reddit posts with comments)
  - `matched-articles` — processed, summarised GDELT articles ready for alert delivery
  - `sub-theme-events` — sub-theme state change events published by the discovery job, consumed by the Alert Service
- Messages are retained for 7 days on `raw-articles`, 1 day on `matched-articles` and `sub-theme-events`
- The multi-consumer pattern on shared streams is the primary reason Kafka was chosen over RabbitMQ. RabbitMQ deletes messages after consumption, making independent consumers on the same stream require duplicate publishing infrastructure. Kafka's consumer offset model handles this natively.

> 📝 **Engineering Note:** Kafka is persistent on disk (unlike Redis Pub/Sub which is in-memory). If your processing pipeline crashes and restarts, it picks up from where it left off using **consumer offsets** — Kafka tracks how far each consumer has read. This is why we chose Kafka over Redis Pub/Sub.

### 2.4 Processing Pipeline
- A Kafka consumer that listens to `raw-articles` 24/7
- Handles two source types with different routing after Stage 3:

| Stage | Method | GDELT | Reddit |
|-------|--------|-------|--------|
| 0. Preprocessing | Clean HTML, generate Sentence-BERT embedding | ✅ | ✅ |
| 1. Deduplication | pgvector ANN search (threshold >= 0.95) | ✅ | ✅ |
| 2. Topic Matching | Cosine similarity vs all active topic embeddings | ✅ | ✅ |
| 3. Store Article | Write to PostgreSQL articles + reddit_comments tables | ✅ | ✅ |
| 4. Summarisation | LangChain + Cohere — called ONCE per article | ✅ | ❌ |
| 5. Publish | Publish to `matched-articles` Kafka topic | ✅ | ❌ |

Reddit articles exit the pipeline after Stage 3. They are stored with their embeddings and comments for use by the sub-theme discovery job, but they never generate user alerts and are never summarised.

- Summarisation runs ONCE per GDELT article — the summary is stored and reused for all users who match that article. Critical for cost control — ~10-15 LangChain + Cohere calls per crawl cycle regardless of user count.
- Publishes matched, summarised GDELT articles to `matched-articles`
- Reads user topics and sensitivity levels from PostgreSQL to perform matching

> 📝 **Engineering Note:** The fail-fast ordering is deliberate — expensive operations run last on the smallest possible dataset. In practice: ~500 raw articles per cycle → ~10-15 reach summarisation. That's ~10-15 external LLM calls per 10 minutes, not 500. This pattern is used in HFT order validation, compiler passes, and data pipelines.

### 2.5 Alert Service
- Consumes from two independent Kafka topics:
  - `matched-articles` — article-level alerts (GDELT articles that matched a user's topic)
  - `sub-theme-events` — intelligence alerts (sub-theme state changes from the discovery job)
- Each stream has its own consumer group and processes independently
- Delivers alerts via three channels:
  - **WebSocket** — instant push. Two event types: `new_alert` (article) and `sub_theme_alert` (intelligence)
  - **Email** — digest only (all pending alerts batched and sent once every 24 hours via Celery Beat)
  - **SMS** — instant via Twilio API
- Writes to `alerts` (article alerts) and `intelligence_alerts` (sub-theme alerts) in PostgreSQL

> 📝 **Engineering Note:** This fan-out pattern (one event → many recipients) is exactly how messaging apps like WhatsApp and push notification services work. The alert service doesn't generate content — it just routes already-processed content to the right users via the right channels.

### 2.6 Sub-theme Discovery Service
- A Celery periodic task (`run_subtheme_discovery`) — not a long-running process and not a Kafka consumer
- Triggered by Celery Beat every `SUBTHEME_DISCOVERY_INTERVAL_HOURS` hours (default: 6)
- Reads from PostgreSQL directly — no Kafka input
- For each active topic, over a rolling `SUBTHEME_WINDOW_DAYS`-day window:
  1. Clusters GDELT article embeddings using HDBSCAN to discover sub-themes
  2. Assigns Reddit posts to the nearest cluster centroid via pgvector similarity search
  3. Runs VADER sentiment analysis over Reddit comments for each cluster (local, no API call)
  4. Calls LangChain + Cohere to generate sub-theme label and description — only when new or significantly changed
  5. Detects meaningful state changes (emerging, growing, disappearing, sentiment shift) vs the prior snapshot
  6. Persists results to `sub_themes`, `sub_theme_memberships`, `sub_theme_snapshots`
  7. Publishes change events to `sub-theme-events` Kafka topic → Alert Service delivers to users

> 📝 **Engineering Note:** The discovery job reads from PostgreSQL rather than consuming from Kafka because sub-theme detection is a **batch operation over a window of history**. It needs to ask "what clusters exist across all articles from the past N days?" — a question that cannot be answered one message at a time. Celery Beat is the correct abstraction for scheduled batch work; Kafka consumers are for real-time per-message stream processing. Using a Kafka consumer here would require accumulating state across thousands of messages in memory with no natural trigger for when to run — the wrong tool entirely.

### 2.7 FastAPI Application
- Single entry point for all client-facing interactions
- Handles:
  - REST API: authenticated user profile, topic management, alert history, intelligence view, preferences
  - Authentication is handled by NextAuth on the Next.js frontend via Google OAuth; FastAPI verifies the shared auth token on protected requests
  - WebSocket: persistent connections for real-time push (both `new_alert` and `sub_theme_alert` events)
- Reads from PostgreSQL to serve dashboard queries
- Does NOT do any processing — it is a pure read/write interface

> 📝 **Engineering Note:** FastAPI is built on Starlette which has native async WebSocket support. This means you don't need a separate Node.js server for real-time features — one Python process handles both REST and WebSocket. This simplifies deployment significantly.

### 2.8 PostgreSQL + pgvector
- Single permanent database for all structured data
- pgvector extension adds vector similarity search natively inside PostgreSQL
- Stores:
  - Users and authentication
  - Topics and alert sensitivity per user
  - Processed articles with embeddings (vector column)
  - Reddit comments (for sentiment analysis)
  - Sub-themes, memberships, and snapshots (intelligence layer)
  - Alert history (article alerts + intelligence alerts)
- Embeddings stored here allow both deduplication (articles) and centroid proximity search (sub-theme assignment)

> 📝 **Engineering Note:** We chose pgvector over a separate vector database (Pinecone, Weaviate) because our vector search needs are moderate — similarity queries against a small number of tables. Adding a dedicated vector DB would mean two databases to manage, two connection pools, two failure points. pgvector keeps it in one place with no extra infrastructure. The centroid similarity search for Reddit-to-sub-theme assignment is a new vector query added in the intelligence layer — still comfortably within pgvector's capabilities at our scale.

---

### 2.9 Raw Article Storage — Kafka Only
- Kafka's 7-day message retention on the raw-articles topic serves as the raw storage layer
- If any consumer crashes and restarts, it replays from its last offset — no separate raw store needed

> 📝 **Engineering Note:** This is a deliberate simplification. Every additional datastore is another failure point, another connection pool, another thing to monitor. If Kafka retention satisfies the replayability requirement — and it does — no extra raw datastore is needed.

---

## 3. Data Flow

### 3.1 Ingestion Flow
```
Celery scheduler (every 10 mins)
        ↓ triggers
Ingestion service
        ↓ fetches from
RSS feeds / Reddit API / Hacker News API
        ↓ publishes raw article to
Kafka: raw-articles topic
```

### 3.2 Processing Flow
```
Kafka: raw-articles topic
        ↓ consumed by
Processing pipeline (always listening)
        ↓
Stage 1: Deduplication
  → duplicate? discard. new? continue.
        ↓
Stage 2: Topic matching
  → similarity below the system threshold? discard. match found? continue.
        ↓
Stage 3: Store matched article and scores in PostgreSQL
  → GDELT: article + topic matches stored
  → Reddit: article + topic matches + comments stored
  → Reddit: EXIT pipeline here (no summarisation, no alert)
        ↓ (GDELT only)
Stage 4: Summarisation (LangChain + Cohere — called ONCE per GDELT article)
  → summary stored in PostgreSQL
        ↓
Stage 5: Publish to matched-articles
  → one message per matched (article, topic, user)
        ↓ publishes to
Kafka: matched-articles topic
```

### 3.3 Alert Delivery Flow
```
Kafka: matched-articles topic
        ↓ consumed by
Alert service (stream A)
        ↓ queries PostgreSQL
"What channels are active for this user's matched topic?"
        ↓ fan-out per configured channel
WebSocket (instant) → new_alert event to connected clients
Email (digest)      → batched via Celery Beat, sent once every 24 hours
SMS (instant)       → Twilio API
        ↓
alert history written to alerts table in PostgreSQL
```

### 3.4 Sub-theme Intelligence Flow
```
Celery Beat — every SUBTHEME_DISCOVERY_INTERVAL_HOURS hours
        ↓ triggers
run_subtheme_discovery task
        ↓ reads from PostgreSQL (GDELT embeddings + Reddit posts + comments)
Cluster GDELT embeddings per topic → HDBSCAN → sub-themes
Assign Reddit posts to nearest centroid → pgvector ANN
Run VADER sentiment on Reddit comments per sub-theme
Call LangChain + Cohere for label/description (only when new or changed)
Detect evolution vs previous snapshot
        ↓ writes to
PostgreSQL: sub_themes, sub_theme_memberships, sub_theme_snapshots
        ↓ publishes change events to
Kafka: sub-theme-events topic
        ↓ consumed by
Alert service (stream B)
        ↓ fan-out per configured channel
WebSocket (instant) → sub_theme_alert event
Email (digest)      → batched with article alerts at midnight
SMS (instant)       → Twilio API
        ↓
intelligence alert history written to intelligence_alerts table
```

### 3.5 User Query Flow (Dashboard)
```
User / client
        ↓ HTTP request
FastAPI (REST API)
        ↓ reads from
PostgreSQL
        ↓ returns
Alert history, topic list, article summaries,
sub-theme intelligence view, timeline snapshots
```

---

## 4. Tech Stack Decisions

| Component | Technology | Decision Rationale |
|-----------|------------|-------------------|
| Backend framework | FastAPI (Python) | Native async, WebSocket support, NLP/ML ecosystem |
| Task scheduler | Celery + Redis | Production-grade distributed job scheduling, independent of API process |
| Message queue | Apache Kafka | Persistent on disk, replayable, decouples all pipeline stages |
| Database | PostgreSQL + pgvector | Relational queries + vector similarity in one system, no extra infra |
| Raw article storage | Kafka (7-day retention) | Replayable by design — no extra datastore needed |
| News source | GDELT REST API | Free, no auth, global news coverage from thousands of outlets — replaces fixed RSS list |
| Social source | Reddit API (PRAW) | Posts + comments in one call; comments drive sentiment analysis |
| Pipeline embedding | Sentence-BERT (local) | Text similarity — no generation needed, free, fast, no API latency |
| Summarisation | LangChain + Cohere | Language generation for GDELT articles only, ~10-15 calls per cycle |
| Sub-theme clustering | HDBSCAN (local) | Discovers cluster count automatically — K-means requires fixed K which is unknowable |
| Sentiment analysis | VADER (local) | Rule-based, designed for social media text, microsecond latency, no API cost |
| Sub-theme labeling | LangChain + Cohere | Called only when sub-theme is new or significantly changed — minimal calls |
| Alert: real-time | FastAPI WebSocket | Built into FastAPI/Starlette, no extra server needed |
| Alert: email | SMTP (via FastAPI + Celery) | Standard, no third-party dependency for v1 |
| Alert: SMS | Twilio API | Industry standard, simple REST API |

---

## 5. Key Architectural Decisions

### 5.1 Event-driven over request-driven
Components communicate via Kafka events, not direct function/HTTP calls. This means each component can fail and recover independently without affecting others.

### 5.2 Crawl broadly, filter locally
The ingestion service crawls sources once and publishes everything. Topic matching happens in the processing pipeline, not at crawl time. This prevents N×M API calls (N users × M topics).

### 5.3 Summarise once, reuse everywhere
The summarization LLM is called once per article that passes all filters. The summary is stored in PostgreSQL and reused for every user who receives that article as an alert. This keeps external LLM calls to ~10-15 per crawl cycle regardless of user count.

### 5.4 Availability over consistency (AP system)
During failures, the system prefers returning slightly stale data over returning nothing. A news alert arriving 2 minutes late is acceptable. A broken dashboard is not.

### 5.5 pgvector over dedicated vector database
Vector search for deduplication runs inside PostgreSQL via pgvector. A dedicated vector DB (Pinecone, Weaviate) would add infrastructure complexity without meaningful performance benefit at our scale (10k users, ~500 articles/cycle).

### 5.6 Kafka over Redis Pub/Sub
Kafka persists messages to disk with configurable retention (7 days). If any consumer crashes and restarts, it resumes from its last offset. Redis Pub/Sub drops messages if no consumer is listening — unacceptable for an alert system.

### 5.7 Batch processing over stream processing for sub-theme discovery
Sub-theme discovery is a periodic batch job (Celery Beat) that reads a window of history from PostgreSQL, not a Kafka stream consumer. Stream processing answers "what just happened?" — the right tool for per-article alerts. Batch processing answers "what patterns exist across the last N days?" — the right tool for clustering. Using a Kafka consumer for sub-theme discovery would require accumulating stateful history across thousands of messages with no natural trigger — the wrong abstraction entirely.

### 5.8 Source separation — GDELT for clustering, Reddit for sentiment
GDELT article headlines produce semantically clean embeddings because they describe events directly. Reddit post titles are often reactions ("This is insane", "Thoughts?") — noisier embeddings that would distort cluster shapes. Clusters are formed from GDELT only; Reddit posts are assigned by centroid proximity after clustering. Reddit comments then provide sentiment signal per sub-theme. This separation keeps both the clustering and the sentiment inputs at their highest quality.

---

## 6. Out of Scope for HLD

The following are deferred to Phase 3 (Low-Level Design):
- Database schema (table definitions, indexes, foreign keys)
- API contracts (endpoint definitions, request/response shapes)
- Kafka topic configuration (partitions, replication factor, retention policy)
- Sentence-BERT model choice and embedding dimensions
- Rate limiting and API security
- Celery task retry configuration

---

> This document was produced as part of Phase 2 of the engineering process.
> Next: Phase 3 — Low-Level Design (LLD)
