# Celery Task Design — Low-Level Design

> **Section:** 3.7 — Celery Task Design
> **Phase:** 3 — Low-Level Design
> **Depends on:** schema.sql, high-level-design.md, kafka-lld.md, alert-service-lld.md

---

## Table of Contents

1. [Overview](#1-overview)
2. [Task Inventory](#2-task-inventory)
3. [Ingestion Tasks](#3-ingestion-tasks)
   - 3.1 [Task Pattern](#31-task-pattern)
   - 3.2 [Standard Article Format](#32-standard-article-format)
   - 3.3 [Fault Isolation](#33-fault-isolation)
   - 3.4 [RSS vs API Sources](#34-rss-vs-api-sources)
4. [Beat Schedule](#4-beat-schedule)
5. [Retry Configuration](#5-retry-configuration)
6. [Infrastructure — Local vs Production](#6-infrastructure--local-vs-production)
   - 6.1 [Local Development (Docker Compose)](#61-local-development-docker-compose)
   - 6.2 [Production Deployment](#62-production-deployment)
7. [How Services Connect](#7-how-services-connect)

---

## 1. Overview

Celery has two responsibilities in this system:

1. **Ingestion scheduling** — polling RSS feeds, Reddit, and Hacker News every 10 minutes via Celery Beat
2. **Async task execution** — SMS delivery with retry logic (designed in `alert-service-lld.md`, referenced here, not repeated)

**Beat vs Worker — two separate processes:**

Celery Beat and Celery Worker are distinct processes with distinct roles. Beat is a scheduler — it fires task messages on a cron schedule. Worker is an executor — it watches for those messages and runs the task code. Neither can do the other's job.

```
Celery Beat (scheduler)
  → publishes task message to Redis at each scheduled interval
    → Celery Worker (executor)
        → picks up message from Redis
        → runs the task function
```

**Redis as the message broker:**

Redis sits between Beat and Worker. Beat drops task messages into Redis; Worker watches Redis and picks them up. Without Redis running, Beat and Worker cannot communicate — tasks silently pile up in the scheduler and are never executed.

Redis uses logical database separation to keep concerns clean:

| Redis DB | Purpose |
|----------|---------|
| `db=0` | Celery broker (task queue) |
| `db=1` | WebSocket tickets (used by FastAPI auth) |

Same Redis instance, zero interference between the two uses. This is acceptable at v1 scale — separate Redis instances are a v2 concern.

> 📝 **Engineering Note:** Celery Beat does not run tasks itself. It only emits task messages. A common source of confusion is running Beat without a Worker — the schedule fires as expected but nothing actually executes. Both processes must be running.

---

## 2. Task Inventory

Every Celery task in the system:

| Task Name | Triggered By | Purpose |
|-----------|-------------|---------|
| `crawl_bbc` | Beat, every 10 min | Fetch BBC RSS feed |
| `crawl_techcrunch` | Beat, every 10 min | Fetch TechCrunch RSS feed |
| `crawl_google_news` | Beat, every 10 min | Fetch Google News RSS feed |
| `crawl_reuters` | Beat, every 10 min | Fetch Reuters RSS feed |
| `crawl_reddit` | Beat, every 10 min | Fetch Reddit API (4 subreddits) |
| `crawl_hackernews` | Beat, every 10 min | Fetch HN top stories via Algolia API |
| `dispatch_sms_task` | Alert Service | Send SMS via Twilio with retry |
| `send_email_digest` | Beat, midnight UTC | Sweep pending email alerts, send digest |

`dispatch_sms_task` and `send_email_digest` are designed and documented in detail in `alert-service-lld.md` Sections 8 and 9. They appear here for completeness and are not repeated.

---

## 3. Ingestion Tasks

### 3.1 Task Pattern

All six crawl tasks follow the same structure. The implementation below uses `crawl_bbc` as the representative example — the pattern is identical for all sources:

```python
@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30
)
def crawl_bbc(self):
    try:
        # Step 1: Fetch raw data from source
        # Step 2: Parse and normalize into standard article format
        # Step 3: Publish each article to Kafka raw-articles topic
    except Exception as e:
        raise self.retry(exc=e, countdown=self._get_backoff_delay())

def _get_backoff_delay(self):
    # Attempt 1 → immediate
    # Attempt 2 → 30 seconds
    # Attempt 3 → 60 seconds
    # Attempt 4 → 120 seconds → give up, log error
    delays = [0, 30, 60, 120]
    return delays[min(self.request.retries, len(delays) - 1)]
```

`bind=True` gives the task access to `self`, which is required to call `self.retry()` and to read `self.request.retries` for backoff calculation.

### 3.2 Standard Article Format

Every crawl task normalises its source-specific data into the same JSON structure before publishing to Kafka. This is the `raw-articles` message contract — it matches `kafka-lld.md` Section 5.1 and `pipeline-lld.md` Section 3 exactly:

```json
{
  "url": "https://...",
  "headline": "Article headline",
  "content": "Full article text",
  "source_id": "<uuid>",
  "published_at": "2026-03-20T09:00:00Z"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `url` | string | Unique identifier — used for URL-based dedup in pipeline Stage 1 |
| `headline` | string | Combined with content for embedding in pipeline Stage 0 |
| `content` | string | Raw HTML or plain text from source |
| `source_id` | UUID | Maps to `sources` table; used to fetch `credibility_score` |
| `published_at` | ISO 8601 | May be null — many RSS feeds omit this field |

> 📝 **Engineering Note:** The normalisation step is the ingestion service's only non-trivial logic. Every source publishes in a different shape (RSS XML, JSON API, PRAW objects). The task's job is to absorb that variation and emit a consistent contract downstream. The pipeline never needs to know which source an article came from.

### 3.3 Fault Isolation

Each source has its own independent Celery task. This is deliberate:

- A failure in `crawl_reddit` does not affect `crawl_bbc`
- Each task retries independently on its own backoff schedule
- After max retries, the task logs the error and exits — no further action
- The next crawl cycle runs in 10 minutes regardless

Missing one crawl cycle per source is an acceptable outcome. At 10-minute intervals, the next successful crawl will pick up any articles published during the gap. This is a "crawl broadly, tolerate gaps" design — consistent with the AP system tradeoff documented in `high-level-design.md`.

> 📝 **Engineering Note:** Fault isolation is why there are six separate tasks instead of one `crawl_all` task. A single task that fetches all sources would mean a single Reddit API timeout blocks the entire ingestion cycle. Six independent tasks mean six independent failure domains.

### 3.4 RSS vs API Sources

**RSS sources (BBC, TechCrunch, Google News, Reuters):**
- Parse XML feed using the `feedparser` library
- Extract: `title`, `link`, `summary`, `published` date
- No authentication required

**Reddit:**
- Use PRAW (Python Reddit API Wrapper)
- Fetch top 25 posts from each of 4 subreddits: `r/technology`, `r/worldnews`, `r/science`, `r/MachineLearning`
- Requires Reddit API credentials (`client_id`, `client_secret`) — stored as environment variables

**Hacker News:**
- Use the Algolia HN Search API — free, no authentication required
- Fetch top 100 stories
- Endpoint: `http://hn.algolia.com/api/v1/search?tags=front_page`

### 3.5 Adding a New Source

When a teammate implements a new crawl task:

1. **Set `is_active = TRUE`** for the source row in the seed data (`schema.sql`)
2. **Hardcode the `source_id`** from the seed data as a constant in the task file — do not query the DB for it
3. **Write the crawl task** following the pattern in Section 3.1 — fetch, normalise to the standard 5-field format, publish to `raw-articles`
4. **Register it in the Beat schedule** (Section 4) with `crontab(minute="*/10")`
5. **Add it to the task inventory table** (Section 2)

The only contract a crawl task must honour is the output format defined in Section 3.2. The pipeline has no knowledge of which source an article came from beyond `source_id`.

---

## 4. Beat Schedule

```python
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    # Ingestion tasks — all every 10 minutes
    "crawl-bbc": {
        "task": "tasks.crawl_bbc",
        "schedule": crontab(minute="*/10"),
    },
    "crawl-techcrunch": {
        "task": "tasks.crawl_techcrunch",
        "schedule": crontab(minute="*/10"),
    },
    "crawl-google-news": {
        "task": "tasks.crawl_google_news",
        "schedule": crontab(minute="*/10"),
    },
    "crawl-reuters": {
        "task": "tasks.crawl_reuters",
        "schedule": crontab(minute="*/10"),
    },
    "crawl-reddit": {
        "task": "tasks.crawl_reddit",
        "schedule": crontab(minute="*/10"),
    },
    "crawl-hackernews": {
        "task": "tasks.crawl_hackernews",
        "schedule": crontab(minute="*/10"),
    },
    # Email digest — midnight UTC daily
    "send-email-digest": {
        "task": "tasks.send_email_digest",
        "schedule": crontab(hour=0, minute=0),
    },
}
```

All six ingestion tasks fire at the same interval (`*/10`). They do not coordinate or wait for each other — each fires independently and runs to completion (or failure) on its own.

> 📝 **Engineering Note:** `crontab(minute="*/10")` fires at 0, 10, 20, 30, 40, 50 minutes past every hour. All six tasks fire at exactly the same moments. This is intentional — there is no benefit to staggering them. Each task runs in parallel on the Worker and fetches from a different external source, so they do not contend for any shared resource.

---

## 5. Retry Configuration

| Task | Max Retries | Backoff | Rationale |
|------|------------|---------|-----------|
| `crawl_*` (all 6 sources) | 3 | 0s → 30s → 60s → 120s | Source outages are transient; next crawl cycle runs in 10 min regardless |
| `dispatch_sms_task` | 3 | 0s → 60s → 300s → 1800s | Twilio outages last minutes, not seconds — slow backoff gives time to recover |
| `send_email_digest` | 0 | None | Recovery is built into the data model — see note below |

**Engineering note for `send_email_digest` — why zero retries:**

No retries are needed because the recovery mechanism is already in the database. All unsent email alerts sit in the `alerts` table with `status = 'pending'`. If the midnight job fails entirely, the next midnight run queries `WHERE channel = 'email' AND status = 'pending'` and picks up everything — including any alerts missed from prior failed runs. No data loss occurs; at most a 24-hour delay. Adding retry logic would solve a problem the schema already handles.

> 📝 **Engineering Note:** The crawl task backoff (30s → 60s → 120s) is deliberately short compared to the SMS backoff (60s → 300s → 1800s). RSS and API sources tend to recover quickly from transient errors (rate limits, brief timeouts). Twilio outages are infrastructure-level failures that last much longer. Matching the backoff duration to the typical failure duration maximises the chance of a successful retry.

---

## 6. Infrastructure — Local vs Production

### 6.1 Local Development (Docker Compose)

Three services are required alongside the existing `backend` service: `celery-worker`, `celery-beat`, and `redis`. All share the same Docker image built from the application's `Dockerfile`.

```yaml
services:
  backend:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./:/app
    environment:
      - REDIS_URL=redis://redis:6379/0
      - KAFKA_BOOTSTRAP_SERVERS=<confluent-cloud-url>
    depends_on:
      - redis

  celery-worker:
    build: .
    command: celery -A app.celery_app worker --loglevel=info
    volumes:
      - ./:/app
    environment:
      - REDIS_URL=redis://redis:6379/0
      - KAFKA_BOOTSTRAP_SERVERS=<confluent-cloud-url>
    depends_on:
      - redis

  celery-beat:
    build: .
    command: celery -A app.celery_app beat --loglevel=info
    volumes:
      - ./:/app
    environment:
      - REDIS_URL=redis://redis:6379/0
      - KAFKA_BOOTSTRAP_SERVERS=<confluent-cloud-url>
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

**Two notes on this setup:**

Kafka is **not** run locally. All environments — local development and production — connect to Confluent Cloud free tier. This avoids running a heavy Kafka container locally (Kafka + ZooKeeper or KRaft adds significant memory overhead). Confluent Cloud free tier is sufficient for development volumes.

A PostgreSQL container should also be present in `docker-compose.yml`. It is omitted above as it is managed by the teammate handling database setup — see `schema.sql`.

### 6.2 Production Deployment

Two options are documented. Option A is recommended for v1.

**Option A — Single VM (Recommended):**

One $5–6/month DigitalOcean Droplet or Railway VM. Run all services via Docker Compose on the VM using the same `docker-compose.yml` as local development. No spin-down problem, full control, cheapest option for v1 scale.

```
VM
└── docker compose up
    ├── backend (FastAPI + Alert Service)
    ├── celery-worker
    ├── celery-beat
    ├── redis
    └── postgres
```

Kafka stays on Confluent Cloud.

**Option B — Render:**

Render's free tier spins down services after 15 minutes of inactivity. This breaks both Celery Worker and Beat — scheduled crawls stop running entirely when the service is dormant. If using Render, the paid tier is required ($7/month per service).

Three separate Render services, all deployed from the same GitHub repository:

| Render Service | Start Command |
|----------------|--------------|
| Web Service | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Background Worker | `celery -A app.celery_app worker --loglevel=info` |
| Background Worker | `celery -A app.celery_app beat --loglevel=info` |

Use Render's managed Redis for the broker and Confluent Cloud for Kafka.

> 📝 **Engineering Note:** Option A and Option B produce identical runtime behaviour. The difference is purely operational: Option A is cheaper and simpler to operate; Option B trades cost for managed infrastructure. For a v1 system with one team, Option A is the right default. Render becomes attractive when you want to stop managing a VM entirely.

---

## 7. How Services Connect

**Local Development:**

```
celery-beat container
  → drops task message into Redis container (redis://redis:6379/0)
    → celery-worker container picks up task
      → worker fetches from RSS / Reddit / HN (external network calls)
        → worker publishes article to Confluent Cloud Kafka (raw-articles topic)
          → Processing Pipeline consumes from Confluent Cloud Kafka
```

**Production (Single VM, Option A):**

Identical to local development. All containers run on one VM via Docker Compose. Redis is on the same VM; Kafka is on Confluent Cloud. No architectural difference from local — only the VM hostname changes.

**Environment Variables required:**

```
REDIS_URL                = redis://redis:6379/0            # local
                         = <managed-redis-url>             # production (Render option)

KAFKA_BOOTSTRAP_SERVERS  = <confluent-cloud-bootstrap-url>
KAFKA_API_KEY            = <confluent-cloud-api-key>
KAFKA_API_SECRET         = <confluent-cloud-api-secret>

REDDIT_CLIENT_ID         = <reddit-app-client-id>
REDDIT_CLIENT_SECRET     = <reddit-app-client-secret>
```

Twilio and email credentials (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, SMTP settings) are also required at runtime but are defined and documented in `alert-service-lld.md`.

> 📝 **Engineering Note:** The Kafka environment variables are the same across local development and production because both environments connect to the same Confluent Cloud cluster. There is no "local Kafka" — this simplifies configuration and eliminates the class of bugs that arise from local-vs-prod infrastructure divergence.

---

> This document was produced as part of Phase 3 (Low-Level Design).
> Depends on: `schema.sql`, `high-level-design.md`, `kafka-lld.md`, `alert-service-lld.md`
