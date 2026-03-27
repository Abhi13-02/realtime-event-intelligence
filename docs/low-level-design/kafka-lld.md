# Kafka Configuration — Low-Level Design

> **Section:** 3.5 — Kafka Configuration
> **Phase:** 3 — Low-Level Design
> **Depends on:** high-level-design.md, pipeline-lld.md

---

## Table of Contents

1. [Overview](#1-overview)
2. [Topics](#2-topics)
   - 2.1 [raw-articles](#21-raw-articles)
   - 2.2 [matched-articles](#22-matched-articles)
3. [Producer Configuration](#3-producer-configuration)
   - 3.1 [Ingestion Service Producer](#31-ingestion-service-producer-raw-articles)
   - 3.2 [Pipeline Producer](#32-pipeline-producer-matched-articles)
4. [Consumer Configuration](#4-consumer-configuration)
   - 4.1 [Processing Pipeline Consumer](#41-processing-pipeline-consumer)
   - 4.2 [Alert Service Consumer](#42-alert-service-consumer)
5. [Message Contracts](#5-message-contracts)
   - 5.1 [raw-articles message](#51-raw-articles-message)
   - 5.2 [matched-articles message](#52-matched-articles-message)
6. [Broker Configuration](#6-broker-configuration)
7. [Error Handling](#7-error-handling)
8. [Monitoring Signals](#8-monitoring-signals)

---

## 1. Overview

Kafka acts as the central message bus connecting all backend services. No service calls another service directly — they communicate exclusively through Kafka topics.

**Two topics are used:**

| Topic | Publisher | Consumer(s) | Purpose |
|-------|-----------|-------------|---------|
| `raw-articles` | Ingestion Service | Processing Pipeline, Analytics Consumer | Raw crawled articles waiting to be processed |
| `matched-articles` | Processing Pipeline | Alert Service | Processed, summarised, matched articles ready for alert delivery |

**Why Kafka and not direct HTTP calls?**
If the pipeline was down, HTTP calls from the ingestion service would either fail silently or need complex retry logic. With Kafka, the ingestion service just publishes and moves on. When the pipeline comes back up, it replays all messages it missed — zero message loss.

---

## 2. Topics

### 2.1 `raw-articles`

Holds raw, unprocessed articles published by the ingestion service.

```
Topic name:          raw-articles
Partitions:          3
Replication factor:  1          (single broker for v1; increase to 3 for prod)
Retention:           7 days     (168 hours)
Retention policy:    delete     (old messages are deleted after 7 days)
Max message size:    1 MB       (more than enough for a full article + metadata)
```

**Why 3 partitions?**
Partitions are the unit of parallelism in Kafka. With 3 partitions, you can run up to 3 parallel pipeline consumer instances if processing falls behind. For v1 with ~500 articles per crawl cycle, 1 consumer is sufficient — but the partitions are pre-provisioned so you can scale horizontally without recreating the topic.

**Why 7-day retention?**
This is your raw storage layer (replacing MongoDB). If the pipeline crashes for several hours, Kafka holds the articles. On restart, the consumer replays from its last committed offset. 7 days is generous enough to cover any realistic failure scenario.

> 📝 **Engineering Note:** Retention is by time (`retention.ms`), not by number of messages. Old messages are deleted **only after** the retention period, regardless of whether they have been consumed. This is fundamentally different from RabbitMQ, where messages are deleted after the first consumer reads them.

---

### 2.2 `matched-articles`

Holds processed, summarised, and matched articles ready for alert delivery.

```
Topic name:          matched-articles
Partitions:          3
Replication factor:  1          (single broker for v1)
Retention:           1 day      (24 hours)
Retention policy:    delete
Max message size:    64 KB      (small payload — IDs + scores only, no content)
```

**Why 1-day retention (not 7)?**
Messages on this topic are lightweight routing instructions containing only IDs. Once the Alert Service has consumed a message and delivered the alert, the message has no further value. 1-day retention covers any Alert Service downtime without wasting disk space storing ID payloads indefinitely.

> 📝 **Engineering Note:** Shorter retention on `matched-articles` vs `raw-articles` is intentional. Raw content has replay value (you might want to reprocess missed articles). Alert routing payloads have no replay value after successful delivery.

---

## 3. Producer Configuration

### 3.1 Ingestion Service Producer (`raw-articles`)

The ingestion service publishes one message per crawled article.

```python
producer_config = {
    "bootstrap.servers": "localhost:9092",

    # Durability
    "acks": "1",               # Leader broker acknowledges write (not all replicas)
                               # Acceptable for raw articles — if a message is lost,
                               # the next crawl cycle will re-fetch the article anyway

    # Batching (throughput optimisation)
    "linger.ms": 100,          # Wait up to 100ms to batch messages before sending
    "batch.size": 16384,       # 16KB batch — articles arrive in bursts every 10 mins

    # Serialisation
    "value.serializer": "json",

    # Idempotence (duplicate prevention during retries)
    "enable.idempotence": False  # Not needed — ingestion service handles dedup at URL level
}
```

**`acks=1` for raw articles:**
`acks=all` waits for all replica brokers to confirm the write — safer but slower. For v1 with a single broker, there are no replicas, so `acks=all` and `acks=1` are equivalent. Using `acks=1` is documented here so the intention is explicit when scaling to multiple brokers.

> 📝 **Engineering Note:** `linger.ms=100` means the producer waits up to 100ms before flushing a batch. Since articles arrive in bulk every 10 minutes (not one-at-a-time continuously), this allows batching the burst and sending it efficiently rather than 500 individual network calls.

---

### 3.2 Pipeline Producer (`matched-articles`)

The processing pipeline publishes one message per (article, topic) pair that passes all filters.

```python
producer_config = {
    "bootstrap.servers": "localhost:9092",

    # Durability — stricter than ingestion
    "acks": "1",

    # Retries — critical: if the broker is temporarily unavailable, retry
    "retries": 3,
    "retry.backoff.ms": 500,

    # Ordering guarantee within a topic partition
    "max.in.flight.requests.per.connection": 1,  # Prevents reordering during retries

    # Serialisation
    "value.serializer": "json"
}
```

**Why stricter retry config here vs ingestion?**
A lost `raw-articles` message is tolerable — the article will be re-crawled in the next cycle. A lost `matched-articles` message means a user never receives an alert they should have gotten. This is the main user-facing delivery path, so retries are essential.

---

## 4. Consumer Configuration

### 4.1 Processing Pipeline Consumer

Reads from `raw-articles`. This is the most critical consumer — it must process every article exactly at least once.

```python
consumer_config = {
    "bootstrap.servers": "localhost:9092",
    "group.id": "pipeline-consumer-group",

    # Offset management — MANUAL. Do not auto-commit.
    "enable.auto.commit": False,

    # Where to start if no committed offset exists (fresh start or reset)
    "auto.offset.reset": "earliest",  # Process all available messages from the beginning

    # Throughput — small batch: pipeline is CPU/GPU-heavy per article
    "max.poll.records": 10,           # Process 10 articles per poll loop

    # Session timeout — how long before Kafka considers this consumer dead
    "session.timeout.ms": 30000,      # 30 seconds
    "heartbeat.interval.ms": 10000    # Send heartbeat every 10 seconds
}
```

**Why `enable.auto.commit = False`?**
This is the most important consumer setting. With auto-commit, Kafka marks a message as "processed" automatically on a timer — even if your processing code crashed halfway through. With manual commit, you only mark a message "done" after the pipeline has fully processed it and written to PostgreSQL. If the process crashes mid-article, Kafka replays that article on restart.

**Commit point:**
```python
# After successful processing of an article:
consumer.commit()  # Only called AFTER PostgreSQL write and Kafka publish succeed
```

**Why `max.poll.records = 10`?**
The pipeline runs Sentence-BERT locally and calls Gemini externally per article. Processing 10 articles before polling again is a reasonable batch size — low enough to commit frequently (limiting replay on crash), high enough to avoid constant Kafka polling overhead.

> 📝 **Engineering Note:** `session.timeout.ms` must be greater than `heartbeat.interval.ms`. If the pipeline is busy processing a heavy article for more than 30 seconds without sending a heartbeat, Kafka will declare it dead and reassign its partitions. For a CPU-heavy ML pipeline, tuning this is important — keep it generous.


---

### 4.2 Analytics Consumer (Deferred)

Reads from `raw-articles`. This consumer calculates hourly volume spikes per topic. 
*Note: Because the analytics API and database schema are currently marked as TODO for Phase 2, the exact configuration for this consumer is deferred. It will use its own `group.id` (e.g., `analytics-consumer-group`) so that it reads the `raw-articles` topic completely independently of the Processing Pipeline.*

---

### 4.3 Alert Service Consumer

Reads from `matched-articles`. Delivers alerts to users via WebSocket, email, and SMS.

```python
consumer_config = {
    "bootstrap.servers": "localhost:9092",
    "group.id": "alert-consumer-group",

    # Offset management — also manual for the same reason
    "enable.auto.commit": False,

    "auto.offset.reset": "earliest",

    # Higher throughput than pipeline — alert delivery is lightweight (no ML)
    "max.poll.records": 50,

    "session.timeout.ms": 30000,
    "heartbeat.interval.ms": 10000
}
```

**Why `max.poll.records = 50` (vs 10 for pipeline)?**
Alert delivery is fast compared to ML processing. The alert service fetches an article from PostgreSQL and sends a WebSocket/email/SMS — no heavy computation. Polling 50 at a time is safe and reduces Kafka polling overhead.

**Commit strategy:**
```python
# Commit after EACH alert is successfully dispatched
# Do not batch commits — a crash between dispatches would cause missed alerts
consumer.commit()
```

> 📝 **Engineering Note:** Two consumers (`pipeline-consumer-group` and `alert-consumer-group`) both read from `raw-articles` independently. Kafka tracks a separate offset per consumer group — they never interfere with each other. This is the core reason Kafka was chosen over RabbitMQ.

---

## 5. Message Contracts

### 5.1 `raw-articles` Message

Published by the Ingestion Service. Consumed by the Processing Pipeline.

```json
{
  "url": "https://techcrunch.com/2026/03/20/nvidia-h200",
  "headline": "NVIDIA announces H200 chip",
  "content": "Full article text here...",
  "source_id": "<uuid>",
  "published_at": "2026-03-20T09:00:00Z"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `url` | string | ✅ | Unique identifier — used for URL-based dedup in Stage 1 |
| `headline` | string | ✅ | Combined with content for embedding in Stage 0 |
| `content` | string | ✅ | Raw HTML or plain text from source |
| `source_id` | UUID | ✅ | Maps to `sources` table — used to fetch credibility_score |
| `published_at` | ISO 8601 | ❌ | May be null; many RSS feeds omit this field |

**Partition key:** `source_id`
All messages from the same source land in the same partition. This ensures ordering within a source — if BBC publishes 5 articles in 1 minute, they are processed in publication order.

---

### 5.2 `matched-articles` Message

Published by the Processing Pipeline. Consumed by the Alert Service.

```json
{
  "article_id": "<uuid>",
  "topic_id": "<uuid>",
  "relevance_score": 0.87,
  "user_id": "<uuid>"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `article_id` | UUID | Alert Service uses this to fetch headline, summary, source from PostgreSQL |
| `topic_id` | UUID | Identifies which topic triggered the alert |
| `relevance_score` | float | Cosine similarity score — stored in the `alerts` table row |
| `user_id` | UUID | The user who owns this topic and will receive the alert |

**Why not include the full article in this message?**
The Alert Service needs headline, summary, and source name to build the alert. These are already in PostgreSQL (written in Stage 4). Duplicating them in the Kafka message would:
1. Increase message size from ~200 bytes to ~5KB
2. Create consistency risk if the article is updated after the message is published

The Alert Service fetches fresh data from PostgreSQL using `article_id` — one DB read, always up to date.

**Partition key:** `topic_id` — all alerts for the same topic are processed in order.

---

## 6. Broker Configuration

For v1 (single broker, local development / single VM deployment):

```properties
# server.properties (Kafka broker config)

# Broker identity
broker.id=0

# Network
listeners=PLAINTEXT://0.0.0.0:9092
advertised.listeners=PLAINTEXT://localhost:9092

# Log storage (where messages are persisted on disk)
log.dirs=/var/kafka-logs

# Default retention — overridden per-topic where needed
log.retention.hours=168       # 7 days default
log.retention.check.interval.ms=300000  # Check every 5 minutes for expired segments

# Log segment size — Kafka splits each partition into segment files
log.segment.bytes=1073741824  # 1GB per segment (reasonable for moderate volume)

# Default replication (v1 single broker)
default.replication.factor=1
min.insync.replicas=1

# Kafka 3.7 (KRaft mode) — Zookeeper is not required and was removed in 3.x
# KRaft replaces Zookeeper for metadata management
# process.roles=broker,controller
# node.id=1
# controller.quorum.voters=1@localhost:9093
```

> 📝 **Engineering Note:** Kafka 3.7 uses KRaft mode natively — no Zookeeper dependency. KRaft became production-ready in Kafka 3.3 and Zookeeper support was fully removed in Kafka 4.0. Production deployments (v2+) should use a 3-broker cluster with `replication.factor=3` and `min.insync.replicas=2`. This means a Kafka message is only acknowledged after at least 2 of 3 brokers have written it — survivable against one broker failure with zero data loss.

---

## 7. Error Handling

### 7.1 Producer Errors

| Scenario | Behaviour |
|----------|-----------|
| Broker temporarily unavailable | Retry with backoff (`retries=3`, `retry.backoff.ms=500`) |
| Message exceeds `max.message.bytes` | Log error, skip article, continue crawl |
| Serialisation error | Log error with raw data, skip message |

### 7.2 Consumer Errors — Pipeline

| Scenario | Behaviour |
|----------|-----------|
| PostgreSQL write fails | Retry with exponential backoff (max 3). Do NOT commit offset. Article replayed on restart. |
| Gemini API fails | Retry with exponential backoff (max 3). Do NOT commit offset. |
| Malformed message (missing fields) | Log error. **COMMIT offset.** Malformed messages are not retryable — replaying them forever blocks the partition. |
| Sentence-BERT failure | Do not commit. Let process crash and restart — model reload fixes transient failures. |

### 7.3 Consumer Errors — Alert Service

| Scenario | Behaviour |
|----------|-----------|
| WebSocket delivery fails (user disconnected) | Expected — skip WebSocket, mark alert as `failed` in DB. User will see it when they reconnect via alert history API. |
| Email delivery fails (SMTP error) | Retry via Celery task queue (separate from Kafka). Mark alert `failed` temporarily. |
| SMS delivery fails (Twilio error) | Retry via Celery. Mark alert `failed`. |
| PostgreSQL write fails (writing alert history) | Retry with backoff. Do NOT commit offset. |

> 📝 **Engineering Note:** The key principle: **never commit an offset for a message you haven't fully processed**. A committed offset means "I'm done with this message." If you commit and then crash, Kafka will never replay that message. Uncommitted = guaranteed replay.

---

## 8. Monitoring Signals

These are the Kafka-level metrics worth watching as your system runs:

| Metric | What it means | Alert if... |
|--------|--------------|-------------|
| **Consumer Lag** (`raw-articles`, pipeline group) | How many unprocessed messages are queued | Lag consistently grows → pipeline is slower than ingestion rate |
| **Consumer Lag** (`matched-articles`, alert group) | How many undelivered alert messages are queued | Lag grows → alert service is backed up |
| **Messages In/sec** (`raw-articles`) | Ingestion throughput | Drops to 0 during crawl window → ingestion is failing |
| **Offset Commit Rate** (pipeline group) | How often the pipeline is committing | Drops drastically → pipeline is stuck on a slow/failing article |
| `pipeline_status = 'passed_dedup'` with `summary = NULL` | Articles stuck mid-pipeline (Gemini failures) | Count grows → Gemini API is failing repeatedly |

> 📝 **Engineering Note:** **Consumer lag** is the single most important Kafka health metric. It tells you the pipeline is keeping up with ingestion. If `raw-articles` lag grows indefinitely, you either need to scale pipeline consumers (add more instances) or fix a bottleneck in the pipeline itself.

---

> This document was produced as part of Phase 3 (Low-Level Design).
> Depends on: `high-level-design.md`, `pipeline-lld.md`, `schema.sql`
> Next LLD section: Alert Service LLD
