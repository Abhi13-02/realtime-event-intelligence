# Work Queue — Low-Level Design

> **Section:** 3.5 — Message Transport
> **Phase:** 3 — Low-Level Design
> **Depends on:** high-level-design.md, pipeline-lld.md
> **Replaces:** `kafka-lld.md` (the transport this design removed)

---

## Table of Contents

1. [Why this replaced Kafka](#1-why-this-replaced-kafka)
2. [The table](#2-the-table)
3. [The claim](#3-the-claim)
4. [Queues](#4-queues)
5. [Message contracts](#5-message-contracts)
6. [Producer behaviour](#6-producer-behaviour)
7. [Consumer behaviour](#7-consumer-behaviour)
8. [Failure handling](#8-failure-handling)
9. [Retention](#9-retention)
10. [Monitoring signals](#10-monitoring-signals)
11. [When to outgrow this](#11-when-to-outgrow-this)

---

## 1. Why this replaced Kafka

Kafka carried three streams between four processes. It was removed because the
numbers never justified it.

| Measure | Value |
|---------|-------|
| Ingestion rate | 9 sources × 1 poll / 2 min ≈ **0.15 msg/sec** |
| Pipeline throughput ceiling | ~**1 article/sec per worker** (embedding + LLM bound) |
| Single Kafka broker capacity | 10⁵–10⁶ msg/sec |
| Utilisation | ~**0.0001%** |

Two things follow from that table:

1. **Throughput was never the constraint.** The consumer is roughly 1000× slower
   than the producer, so the queue is almost always empty. Kafka's reason for
   existing — absorbing a firehose a consumer cannot keep up with — never
   engaged.

2. **Every message was already destined for Postgres.** The pipeline writes each
   article to `articles` regardless. Kafka was an extra hop on top of a write
   that happened anyway, not a substitute for it.

Against that, Kafka cost a JVM broker, a `kafka-init` sidecar, a two-listener
Docker configuration, KRaft controller settings, **two** Python client libraries
(`kafka-python` for sync callers, `aiokafka` for async ones), and bootstrap
retry logic that existed only because the broker booted slower than its clients.

The pattern was kept. The infrastructure was not. This is still an event-driven
system: producers do not know their consumers, the hops are asynchronous, and
services fail and restart independently.

**What was genuinely given up:** the durable replayable log. Kafka could rewind a
consumer group to an arbitrary offset and re-read history; this cannot. Nothing
in the system used that, but it is the real trade, and it is the thing to
re-evaluate if a future feature wants to reprocess a week of articles through a
new pipeline stage.

---

## 2. The table

One table backs all three streams. `queue` is the former topic name, so the
streams stay logically separate while sharing one implementation, one reaper and
one retention job.

```sql
CREATE TABLE queue_messages (
    id          BIGSERIAL PRIMARY KEY,
    queue       TEXT        NOT NULL,
    payload     JSONB       NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','processing','done','failed')),
    attempts    INTEGER     NOT NULL DEFAULT 0,
    last_error  TEXT,
    locked_at   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Status lifecycle

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

`failed` is the dead-letter state. It is terminal until a human intervenes.

### The indexes are partial on purpose

```sql
CREATE INDEX idx_queue_messages_claim ON queue_messages (queue, id)
    WHERE status = 'pending';

CREATE INDEX idx_queue_messages_reap  ON queue_messages (queue, locked_at)
    WHERE status = 'processing';

CREATE INDEX idx_queue_messages_prune ON queue_messages (updated_at)
    WHERE status IN ('done', 'failed');
```

Each index contains only rows in the state its query looks for. A queue that has
processed ten million messages but holds forty pending ones has a **forty-row**
claim index. This is what stops a table-as-queue degrading as history
accumulates, and it is the single most important detail in this design.

---

## 3. The claim

```sql
WITH claimed AS (
    SELECT id FROM queue_messages
    WHERE queue = %s AND status = 'pending'
    ORDER BY id
    FOR UPDATE SKIP LOCKED
    LIMIT %s
)
UPDATE queue_messages m
SET status = 'processing', locked_at = NOW(), updated_at = NOW(),
    attempts = m.attempts + 1
FROM claimed c
WHERE m.id = c.id
RETURNING m.id, m.payload, m.attempts;
```

- **`FOR UPDATE`** takes a row-level lock for the life of the transaction. Two
  workers cannot lock the same row — Postgres serialises that internally.
- **`SKIP LOCKED`** makes a concurrent worker step *over* rows another worker
  holds rather than blocking on them. Without it, worker B would wait for worker
  A and the queue would process serially.

Together these are the competing-consumer guarantee that Kafka consumer groups
provided — in one statement, with no partitions to divide and therefore no cap
on replica count. Kafka capped the pipeline at 3 replicas (one per partition).

**Ordering.** `id` is a `BIGSERIAL` and the claim orders by it, so delivery is
insertion order across the whole queue. Kafka gave ordering only *within* a
partition; this is a stronger guarantee, not a weaker one.

**The transaction commits immediately.** Work happens outside it. Holding it open
for the whole job would give free crash recovery via rollback, but a Groq call
takes seconds and that would pin a connection for the duration. Short
transactions plus an explicit reaper is the trade this makes — see §8.

---

## 4. Queues

| Queue | Publisher | Consumer | Purpose |
|-------|-----------|----------|---------|
| `raw-articles` | Ingestion Celery tasks | `pipeline-consumer` | Raw crawled articles (News + Reddit) awaiting processing |
| `matched-articles` | Processing Pipeline (Stage 7) | `alert-consumer` (Stream A) | Processed, summarised articles ready for alert delivery |
| `sub-theme-events` | Sub-theme Discovery Celery task | `alert-consumer` (Stream B) | Sub-theme state changes triggering intelligence alerts |

Names are unchanged from the Kafka topics so logs, dashboards and the rest of the
design docs still line up. They are defined once in
`app/adapters/queue/names.py`.

---

## 5. Message contracts

Payloads are unchanged from the Kafka design — only the transport moved. Each is
stored as `JSONB` in `queue_messages.payload`.

### 5.1 `raw-articles`

```json
{
  "url": "https://techcrunch.com/2026/03/20/nvidia-h200",
  "headline": "NVIDIA announces H200 chip",
  "content": "Full article text here...",
  "source_id": "<uuid>",
  "published_at": "2026-03-20T09:00:00Z",
  "image_url": "https://...",
  "trace_id": "3f2a1b9c"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `url` | string | ✅ | Unique identifier — used for URL dedup in Stage 0 |
| `headline` | string | ✅ | Combined with content for embedding in Stage 1 |
| `content` | string | ✅ | Raw HTML or plain text from source |
| `source_id` | UUID | ✅ | Maps to `sources` — used to fetch `credibility_score` |
| `published_at` | ISO 8601 | ❌ | May be null; many RSS feeds omit it |
| `image_url` | string | ❌ | May be null |
| `trace_id` | string | ✅ | Minted at ingestion; see `app/core/logging.py` |

> Kafka partitioned this stream by `source_id` to preserve per-source order.
> No key is needed now — global `id` ordering subsumes it.

### 5.2 `matched-articles`

```json
{
  "article_id": "<uuid>",
  "topic_id": "<uuid>",
  "relevance_score": 0.87,
  "user_id": "<uuid>",
  "trace_id": "3f2a1b9c"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `article_id` | UUID | Alert Service fetches headline, summary, source from Postgres |
| `topic_id` | UUID | Which topic triggered the alert |
| `relevance_score` | float | Cosine similarity — stored on the `alerts` row |
| `user_id` | UUID | Owner of the topic, recipient of the alert |

**Why not embed the full article?** The Alert Service needs headline, summary and
source name, all already written to Postgres in Stage 5. Duplicating them would
grow the message from ~200 bytes to ~5 KB and create a consistency risk if the
article changed after publication. The consumer reads fresh data by
`article_id` — one query, always current.

### 5.3 `sub-theme-events`

```json
{
  "event_type": "sub_theme_emerging",
  "sub_theme_id": "<uuid>",
  "sub_theme_snapshot_id": "<uuid>",
  "topic_id": "<uuid>",
  "user_id": "<uuid>"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `event_type` | string | `sub_theme_emerging` / `_growing` / `_disappearing` / `_sentiment_shift` |
| `sub_theme_id` | UUID | The sub-theme that changed |
| `sub_theme_snapshot_id` | UUID | Idempotency key in `intelligence_alerts` |
| `topic_id` | UUID | Topic the sub-theme belongs to |
| `user_id` | UUID | Recipient |

---

## 6. Producer behaviour

`app/adapters/queue/publisher.py` — `QueuePublisher`, shared per process via
`get_publisher()`.

**Buffered, then flushed in one statement.** `publish()` appends to an in-memory
buffer; `flush()` writes the whole buffer with a single multi-row `INSERT`. A
crawl cycle producing 450 articles is therefore one statement of roughly 20 ms,
not 450 round trips.

This mirrors the Kafka producer's `linger_ms=100` plus end-of-task `flush()`, and
carries the same durability trade: a process that dies with a full buffer loses
it, exactly as it lost anything still inside `linger_ms`. Neither matters — the
article is re-crawled next cycle, and `articles.url` is `UNIQUE`, so the retry is
idempotent.

`MAX_BUFFERED = 200` forces a flush before the buffer can grow without bound.

**Exception:** `PgEventBus` (`matched-articles`) flushes on every publish. The
pipeline acks its `raw-articles` message only after Stage 7 returns, so an
unflushed buffer would let it ack a message whose matches were never written.

---

## 7. Consumer behaviour

Two implementations, because the callers live in different worlds — the same
reason the Kafka code needed both `kafka-python` and `aiokafka`:

| Class | Driver | Used by |
|-------|--------|---------|
| `PgQueue` | psycopg2 (sync) | `pipeline-consumer`, and every producer |
| `AsyncPgQueue` | SQLAlchemy async session | `alert-consumer` Streams A and B |

Both run the same loop:

```
reap_stalled()  every 60s
claim(batch=10)
  ├─ empty → sleep(2s)
  └─ else  → process each → ack / retry / fail
```

### Why a 2-second poll is not a problem

| | |
|---|---|
| Cost per worker | 0.5 queries/sec, index-only, usually 0 rows |
| 10 workers | 5 queries/sec against a database that handles thousands |
| Added latency | ≤ 2s against a **5-minute** end-to-end budget (0.7%) |

Polling would become a real concern at hundreds of workers, or if the latency
budget dropped below ~1 second. Neither applies. `LISTEN/NOTIFY` is the upgrade
path if it ever does — Postgres's built-in pub/sub, which would let a worker
sleep on the socket and wake on insert, with a slow poll retained as a backstop
for missed notifications.

---

## 8. Failure handling

| Situation | Action | Result |
|-----------|--------|--------|
| Processed successfully | `ack()` | `done` |
| Expected drop (duplicate, no topic match) | `ack()` | `done` — intentional, not a failure |
| Stage 6 summarisation failed | `ack()` | Article already stored with `summary=NULL`; `_resume_pending()` retries on restart |
| Malformed payload (missing field) | `fail()` | `failed` immediately — a missing field will still be missing next time |
| Transient error (DB blip, embedding service restarting) | `retry()` | back to `pending`, `attempts + 1` |
| `attempts` reached `max_attempts` (5) | automatic | `failed` — parked, stops consuming workers |
| Worker process died mid-message | `reap_stalled()` | back to `pending` once `locked_at` exceeds the 300s visibility timeout |

### This is strictly better than what it replaced

Under Kafka, "do not commit the offset" meant the message sat undelivered **until
the container restarted**, and blocked its partition the whole time. There was no
dead-letter state, so a poison message blocked its partition until a human
noticed.

Now a failure retries on the next claim, blocks nothing, and a message that can
never succeed is parked in `failed` where one query finds it:

```sql
SELECT queue, id, attempts, last_error, payload
FROM queue_messages WHERE status = 'failed';
```

### Delivery guarantee

**At-least-once**, the same as the Kafka setup. A worker that crashes after doing
the work but before `ack()` will have its message reaped and redelivered, so
consumers must tolerate seeing a message twice. They do:

- `articles.url` is `UNIQUE`
- `alerts` has `UNIQUE (user_id, article_id, topic_id, channel)`
- `intelligence_alerts` has `UNIQUE (user_id, sub_theme_snapshot_id, alert_type, channel)`
- all three insert with `ON CONFLICT DO NOTHING`

---

## 9. Retention

Kafka expired messages itself via `retention.ms`. That is now a scheduled
`DELETE`: `purge_queue_messages` in `app/tasks/maintenance/retention.py`, run
hourly by Celery Beat with a 10,000-row cap per run so no single pass holds a
long lock.

- **`done`** rows are deleted after **7 days** (matching the old `raw-articles`
  `retention.ms` of 604800000).
- **`failed`** rows are **never** auto-deleted. They are the dead-letter queue;
  ageing them out on a timer would quietly delete evidence of a bug. There should
  be almost none — if there are many, that is the signal, not the storage cost.

---

## 10. Monitoring signals

Everything below is plain SQL, which is itself a gain: Kafka consumer lag needed
broker tooling to see.

| Signal | Query | Healthy |
|--------|-------|---------|
| **Backlog** (the consumer-lag equivalent) | `SELECT queue, count(*) FROM queue_messages WHERE status='pending' GROUP BY queue` | near 0 between crawls |
| **Dead letters** | `SELECT count(*) FROM queue_messages WHERE status='failed'` | 0 |
| **Stuck in flight** | `SELECT count(*) FROM queue_messages WHERE status='processing' AND locked_at < NOW() - INTERVAL '5 minutes'` | 0 (the reaper clears these) |
| **Retry pressure** | `SELECT queue, max(attempts) FROM queue_messages WHERE status='pending' GROUP BY queue` | 1 |
| **Table growth** | `SELECT pg_size_pretty(pg_total_relation_size('queue_messages'))` | stable — retention is working |

`PgQueue.depth(queue)` exposes the backlog to code; both consumers log it at
startup.

---

## 11. When to outgrow this

This design is right for the current load and has substantial headroom, but it is
not the end state. The honest thresholds:

| Throughput | Transport |
|------------|-----------|
| **< 1,000 msg/sec** | **Postgres `SKIP LOCKED`** ← current system, at 0.15 |
| ~1k–10k msg/sec | Redis Streams — real log semantics, already in the stack for Celery |
| ~5k–50k msg/sec | RabbitMQ / SQS — only if complex routing, priorities or DLX machinery is needed |
| > 50k msg/sec, or multi-day replay, or many independent teams reading one stream | Kafka |

**The binding constraint is not the queue.** The pipeline manages ~1 article/sec
per worker because of the embedding and LLM calls. Postgres could feed roughly
1,000 msg/sec, so it would take on the order of 1,000 pipeline workers before the
transport became the bottleneck — and LLM rate limits, GPU capacity and API
budget all bind long before that.

Move off this design when one of these is true, not before:

1. Sustained pending depth that workers cannot drain (real backpressure).
2. A feature that needs to replay history through new logic.
3. Poll latency becoming a measurable share of the end-to-end budget — try
   `LISTEN/NOTIFY` first; it is a much smaller step than a broker.
