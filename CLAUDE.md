# RealTime Event Intelligence — Claude Context

## Project Overview

A multi-tenant, event-driven backend that monitors RSS feeds, Reddit, and Hacker News, runs content through a fail-fast NLP pipeline, and delivers personalised topic alerts via WebSocket, email (digest), and SMS.

## Architecture (Event-Driven)

```
Ingestion Service (Celery)
  → Kafka: raw-articles
    → Processing Pipeline (Kafka consumer)
      → Kafka: matched-articles
        → Alert Service (Kafka consumer, co-located with FastAPI)
FastAPI app — REST + WebSocket (client-facing)
PostgreSQL + pgvector — all persistent data
Redis — Celery broker + WebSocket ticket store
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend framework | FastAPI (Python) |
| Task scheduler | Celery + Redis |
| Message bus | Apache Kafka |
| Database | PostgreSQL 15 + pgvector extension |
| Embeddings | Sentence-BERT `all-MiniLM-L6-v2` (local, 384-dim) |
| Summarisation | Gemini 1.5 Flash API |
| SMS | Twilio REST API |
| Containerisation | Docker + docker-compose |

## Key Design Decisions

- **Crawl broadly, filter locally**: ingestion is topic-agnostic; matching happens in the pipeline
- **Fail-fast pipeline**: cheap stages (dedup, topic match) run before expensive ones (Gemini)
- **Summarise once**: Gemini called once per article; summary stored and reused for all matching users
- **AP system**: availability over consistency — slightly stale data acceptable
- **Alert Service co-located with FastAPI** in v1 (shares `ConnectionManager` for WebSocket push); extract to separate process + Redis Pub/Sub backplane when scaling to multiple instances

## Design Documentation (docs/)

| File | Phase | Status |
|------|-------|--------|
| `docs/requirements.md` | Phase 1 | Draft |
| `docs/high-level-design.md` | Phase 2 | Draft |
| `docs/low-level-design/schema.sql` | Phase 3 | Draft |
| `docs/low-level-design/auth-lld.md` | Phase 3 | Draft |
| `docs/low-level-design/api-contracts.md` | Phase 3 | Draft |
| `docs/low-level-design/pipeline-lld.md` | Phase 3 | Draft |
| `docs/low-level-design/kafka-lld.md` | Phase 3 | Draft |
| `docs/low-level-design/alert-service-lld.md` | Phase 3 | Draft |

## Running Locally

```bash
docker compose up --build
```

## Scale Targets (v1)

- 10,000 concurrent users
- Up to 10 topics per user
- < 5 minute end-to-end alert delivery latency
- 99.9% uptime (three nines)
