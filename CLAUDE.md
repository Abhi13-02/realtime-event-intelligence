# RealTime Event Intelligence — Claude Context

## Project Overview

A multi-tenant, event-driven backend that monitors RSS feeds, Reddit, and Hacker News, runs content through a fail-fast NLP pipeline, and delivers personalised topic alerts via WebSocket, email (24-hour digest, fixed), and SMS.

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
| `docs/requirements.md` | Phase 1 | Complete |
| `docs/high-level-design.md` | Phase 2 | Complete |
| `docs/low-level-design/schema.sql` | Phase 3 | Complete |
| `docs/low-level-design/auth-lld.md` | Phase 3 | Complete |
| `docs/low-level-design/api-contracts.md` | Phase 3 | Complete |
| `docs/low-level-design/pipeline-lld.md` | Phase 3 | Complete |
| `docs/low-level-design/kafka-lld.md` | Phase 3 | Complete |
| `docs/low-level-design/alert-service-lld.md` | Phase 3 | Complete |
| `docs/low-level-design/celery-lld.md` | Phase 3 | Complete |

## Running Locally
```bash
docker compose up --build
```

## Scale Targets (v1)

- 10,000 concurrent users
- Up to 10 topics per user
- < 5 minute end-to-end alert delivery latency
- 99.9% uptime (three nines)

---

## How To Work With Me

I am the driver. Claude Code is my assistant and teacher — not the other way around.

### Core Rules (never break these)

- **Never write or create a file unless I explicitly say "go ahead" or "build this"**
- **Never move to the next step until I confirm I understand the current one**
- **If my approach is wrong or suboptimal, tell me directly — don't silently do it my way**
- **Always explain WHY before HOW AND FOLLOW BEST ENINEERING PRACTICES** — I need to understand the reasoning, not just the output

### How Every Task Should Go

1. I describe what I want to do
2. You explain what's involved and what decisions need to be made
3. We discuss and I decide
4. Only then do you write anything — and only the specific piece we agreed on
5. You explain what you just wrote and why
6. I confirm I understand before we move to the next piece

### Explaining Things

- I don't have deep knowledge of complex infra or DevOps — explain things simply
- Use analogies when something is abstract
- If something has a tradeoff, tell me both sides — don't just pick one silently
- If I ask "why", give me a real answer, not a vague one

### What "Go Ahead" Means

I will explicitly say one of:
- "go ahead and build this"
- "write it"
- "create the file"

Until I say one of those, only discuss and explain. Never assume silence or agreement means go ahead.