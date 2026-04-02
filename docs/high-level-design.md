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
- Polls a fixed curated list of sources (RSS feeds, Reddit, Hacker News) on a schedule
- Runs as a Celery worker — independent of the FastAPI app process
- Publishes raw articles directly to Kafka topic: `raw-articles`
- Has no knowledge of users or topics — it crawls broadly

> 📝 **Engineering Note:** Ingestion is intentionally "dumb" — it just fetches and publishes. This is the **single responsibility principle**: one component, one job. It also means if Reddit's API changes, only the ingestion service needs updating.

### 2.2 Celery + Redis (Scheduler)
- Celery is a distributed task queue — it manages scheduled and async jobs
- Redis acts as the message broker between FastAPI and Celery workers
- Triggers the ingestion service every 10 minutes per source
- Runs independently — if the FastAPI app crashes, polling continues

> 📝 **Engineering Note:** Why not just use a cron job? Cron is fine for simple scripts but doesn't handle retries, failure logging, distributed workers, or dynamic scheduling. Celery gives you all of that. This is the production-grade choice for any Python backend with background jobs.

### 2.3 Kafka
- Central message bus connecting all pipeline stages
- Two topics:
  - `raw-articles` — raw content published by ingestion service
  - `matched-articles` — processed, scored, summarised content ready for alerting
- Messages are retained for 7 days — provides replayability without a separate raw storage database
- Processing pipeline and alert service are Kafka consumers — they are triggered automatically when messages arrive
- Kafka supports multiple independent consumers across topics:
  1. Processing Pipeline — processes articles for alert delivery
  2. Analytics Consumer — tracks hourly volume trends per topic from matched events
- This multi-consumer pattern on a shared stream is the primary reason Kafka was chosen over RabbitMQ. RabbitMQ deletes messages after consumption, making independent consumers on the same stream require duplicate publishing infrastructure. Kafka's consumer offset model handles this natively.

> 📝 **Engineering Note:** Kafka is persistent on disk (unlike Redis Pub/Sub which is in-memory). If your processing pipeline crashes and restarts, it picks up from where it left off using **consumer offsets** — Kafka tracks how far each consumer has read. This is why we chose Kafka over Redis Pub/Sub.

### 2.4 Processing Pipeline
- A Kafka consumer that listens to `raw-articles` 24/7

| Stage | Method | Purpose |
|-------|--------|---------|
| 0. Preprocessing | Clean HTML, extract content, generate Sentence-BERT embedding | Prepares article for all downstream stages |
| 1. Deduplication | Sentence-BERT cosine similarity via pgvector ANN search (threshold >= 0.95) | Removes same article reposted across outlets |
| 2. Topic Matching | Sentence-BERT cosine similarity vs all active topic embeddings (system-defined threshold) | Drops articles irrelevant to any tracked topic |
| 3. Store Article | Write to PostgreSQL articles table | Embedding needed for future deduplication even if no user matches |
| 4. Summarisation | External LLM via LangChain — called ONCE per article | Generates summary stored and reused for all matching users |
| 5. User Sensitivity Filter | Map each topic's sensitivity (`broad`, `balanced`, `high`) to its internal threshold and compare against relevance_score | Routes article to correct users — not a pipeline filter |

> 📝 **Engineering Note:** Novelty detection was deliberately 
removed. For an alert system, recall matters more than 
precision — missing a critical update is a worse user experience 
than occasionally seeing a near-duplicate story. This is the 
same tradeoff Google Alerts makes. Novelty detection can be 
revisited in v2 based on real user feedback about alert fatigue.

- Summarisation runs ONCE per article — the summary is stored 
  and reused for all users who match that article. This is 
  critical for cost control. ~10-15 summarization LLM calls per crawl 
  cycle regardless of user count.
- Publishes matched, summarised articles to Kafka topic: `matched-articles`
- Reads user topics and sensitivity levels from PostgreSQL to perform matching

> 📝 **Engineering Note:** The fail-fast ordering is deliberate — expensive operations run last on the smallest possible dataset. In practice: ~500 raw articles per cycle → ~10-15 reach summarisation. That's ~10-15 external LLM calls per 10 minutes, not 500. This pattern is used in HFT order validation, compiler passes, and data pipelines.

### 2.5 Alert Service
- A Kafka consumer that listens to `matched-articles`
- Receives one already-qualified `(article, topic, user)` match per Kafka message from the pipeline
- Queries PostgreSQL for article details and the active delivery channels configured for that user's topic
- Fan-out: one matched article event → one alert row per configured channel
- Delivers alerts via three channels:
  - **WebSocket** — instant push to connected dashboard clients
  - **Email** — digest only (all alerts batched and sent once every 24 hours via Celery beat; fixed, not configurable)
  - **SMS** — instant via Twilio API
- Writes alert history to PostgreSQL

> 📝 **Engineering Note:** This fan-out pattern (one event → many recipients) is exactly how messaging apps like WhatsApp and push notification services work. The alert service doesn't generate content — it just routes already-processed content to the right users.

### 2.6 FastAPI Application
- Single entry point for all client-facing interactions
- Handles:
  - REST API: authenticated user profile, topic management, alert history, preferences
  - Authentication is handled by NextAuth on the Next.js frontend via Google OAuth; FastAPI verifies the shared auth token on protected requests
  - WebSocket: persistent connections for real-time push alerts
- Reads from PostgreSQL to serve dashboard queries
- Does NOT do any processing — it is a pure read/write interface

> 📝 **Engineering Note:** FastAPI is built on Starlette which has native async WebSocket support. This means you don't need a separate Node.js server for real-time features — one Python process handles both REST and WebSocket. This simplifies deployment significantly.

### 2.7 PostgreSQL + pgvector
- Single permanent database for all structured data
- pgvector extension adds vector similarity search natively inside PostgreSQL
- Stores:
  - Users and authentication
  - Topics and alert sensitivity per user
  - Processed articles with embeddings (vector column)
  - Alert history
- Embeddings stored here allow deduplication across crawl cycles

> 📝 **Engineering Note:** We chose pgvector over a separate vector database (Pinecone, Weaviate) because our vector search needs are moderate — similarity queries against a single table. Adding a dedicated vector DB would mean two databases to manage, two connection pools, two failure points. pgvector keeps it in one place with no extra infrastructure.

---

### 2.8 Raw Article Storage — Kafka Only
- Kafka's 7-day message retention on the raw-articles topic serves as the raw storage layer
- If any consumer crashes and restarts, it replays from its last offset — no separate raw store needed

> 📝 **Engineering Note:** This is a deliberate simplification. 
Every additional datastore is another failure point, another 
connection pool, another thing to monitor. If Kafka retention 
satisfies the replayability requirement — and it does — 
no extra raw datastore is needed.

### 2.9 Analytics Consumer
- An independent Kafka consumer on the matched-articles topic
- Maintains its own consumer offset — completely independent 
  of the alert service consumer
- Every hour, counts articles per matched topic and writes a 
  snapshot row to the trend_snapshots table
- Computes spike_factor by comparing current hour article count 
  against the 7-day rolling baseline for that topic
- Powers the GET /analytics/trends API endpoint
- Has no effect on alert delivery

> 📝 **Engineering Note:** This is the primary architectural 
justification for choosing Kafka over RabbitMQ. Multiple independent 
consumers can read the same logical event stream at their own offsets. 
In this design, the alert service and analytics consumer both read 
`matched-articles` independently. With RabbitMQ, messages are deleted 
after consumption, so adding independent downstream consumers requires 
extra fan-out infrastructure. Kafka's consumer group model handles this 
natively with zero duplication of publishing logic.

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
  → article persisted for deduplication and downstream reuse
        ↓
Stage 4: Summarisation (external LLM via LangChain — called ONCE per article)
  → summary stored in PostgreSQL
        ↓
Stage 5: User sensitivity filter
  → map each topic's sensitivity (`broad`, `balanced`, `high`) to its internal threshold and route alerts only to qualifying users.
        ↓ publishes to
Kafka: matched-articles topic
```

### 3.3 Alert Delivery Flow
```
Kafka: matched-articles topic
        ↓ consumed by
Alert service
        ↓ queries PostgreSQL
"What channels are active for this user's matched topic, and what article details should be delivered?"
        ↓ fan-out per configured channel
WebSocket (instant) → connected dashboard clients
Email (digest)      → batched via Celery beat, sent once every 24 hours
SMS (instant)       → Twilio API
        ↓
Alert history written to PostgreSQL
```

### 3.4 User Query Flow (Dashboard)
```
User / client
        ↓ HTTP request
FastAPI (REST API)
        ↓ reads from
PostgreSQL
        ↓ returns
Alert history, topic list, article summaries
```

---

## 4. Tech Stack Decisions

| Component | Technology | Decision Rationale |
|-----------|------------|-------------------|
| Backend framework | FastAPI (Python) | Native async, WebSocket support, NLP/ML ecosystem |
| Task scheduler | Celery + Redis | Production-grade distributed job scheduling, independent of API process |
| Message queue | Apache Kafka | Persistent on disk, replayable, decouples all pipeline stages |
| Database | PostgreSQL + pgvector | Relational queries + vector similarity in one system, no extra infra |
| Raw article storage | Kafka (7-day retention) | Replayable by design — if any consumer crashes it replays from last offset; no extra datastore needed |
| Stages 0–2 (pipeline) | Sentence-BERT (local) | Text similarity only — no generation needed, free, fast, no API latency |
| Stage 4 (summarisation) | LangChain + Cohere | Language generation required, ~10-15 calls per cycle |
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
