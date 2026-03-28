# Alert Service — Low-Level Design

> **Section:** 3.6 — Alert Service
> **Phase:** 3 — Low-Level Design
> **Depends on:** schema.sql, high-level-design.md, api-contracts.md, kafka-lld.md

---

## Table of Contents

1. [Overview](#1-overview)
2. [Input — Kafka Message Contract](#2-input--kafka-message-contract)
3. [Core Delivery Flow](#3-core-delivery-flow)
4. [Step 1 — Channel Lookup](#4-step-1--channel-lookup)
5. [Step 2 — Bulk Alert Insert](#5-step-2--bulk-alert-insert)
6. [Step 3 — Channel Routing](#6-step-3--channel-routing)
7. [WebSocket Delivery](#7-websocket-delivery)
8. [SMS Delivery — Celery Task](#8-sms-delivery--celery-task)
9. [Email Delivery — Celery Beat Digest](#9-email-delivery--celery-beat-digest)
10. [Error Handling](#10-error-handling)
11. [Full Flow Diagram](#11-full-flow-diagram)

---

## 1. Overview

The Alert Service is a Kafka consumer that listens to the `matched-articles` topic 24/7. When a message arrives, it fans out alerts to all matching users via their configured delivery channels — WebSocket (instant), SMS (instant via Twilio), and email (digest at midnight UTC daily).

**Key principles:**
- Fan-out: one Kafka message → one alert row per channel configured by that user
- Bulk writes: all alert rows inserted in one PostgreSQL statement — no per-row round trips
- Channel isolation: a failure in SMS delivery never affects WebSocket delivery
- Email is digest only: pending email alerts accumulate in PostgreSQL and are swept by a Celery Beat job at midnight UTC
- The alert service does not generate content — it routes already-processed content (headline, summary, source) from PostgreSQL to the right channels

> 📝 **Engineering Note:** The alert service is co-located with the FastAPI app in v1. They share the same process and the same `ConnectionManager` instance for WebSocket delivery. This is intentional — it avoids inter-process communication overhead at v1 scale. When scaling to multiple FastAPI instances, the alert service gets extracted into its own process and uses a Redis Pub/Sub backplane for WebSocket fan-out (already designed in `api-contracts.md` Section 8.3).

---

## 2. Input — Kafka Message Contract

The alert service consumes from the `matched-articles` Kafka topic. Every message conforms to this schema:

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
| `article_id` | UUID | Used to fetch headline, summary, url from PostgreSQL |
| `topic_id` | UUID | Used to look up the user's channel config for this topic |
| `relevance_score` | float | Stored in the alerts table row |
| `user_id` | UUID | The user who owns this topic and will receive the alert |

**Consumer configuration:**
```
group.id = alert-consumer-group
enable.auto.commit = false
auto.offset.reset = earliest
max.poll.records = 50
```

Manual offset commit — same reasoning as the pipeline consumer. An alert that crashes mid-delivery must be replayed, not silently dropped.

---

## 3. Core Delivery Flow

On receiving a Kafka message, the alert service executes these steps in order:

```
1. For the user_id in the message, fetch their channel config for this topic
   → if no active channels (topic deactivated): COMMIT offset and skip — no work to do
2. Fetch article details from PostgreSQL (headline, summary, url, source_name)
3. Bulk INSERT all alert rows into the alerts table (one row per channel)
4. Route each alert to its delivery handler:
     websocket → ConnectionManager.push() directly
     sms       → dispatch Celery task immediately
     email     → leave as pending (Celery Beat picks up at midnight UTC)
5. COMMIT Kafka offset
```

Steps 1–3 happen before any delivery attempt. Channel lookup runs first — if the topic has been deactivated since the pipeline matched it, there are no channels to deliver to and we can exit immediately without fetching the article or writing any rows. If channels exist, the article is fetched and all alert rows are persisted in PostgreSQL before any delivery is attempted. If delivery fails, the alert row already exists — it can be retried without replaying the entire Kafka message.

> 📝 **Engineering Note:** This is the same write-ahead principle used in the pipeline (Stage 4 before Stage 5). Persist first, then attempt the external operation. If the external call fails, you have a recovery path in the database.

> ⚠️ **Offset commit timing:** The Kafka offset is committed **after all three channels have been routed** (step 5) — not after delivery is confirmed. "Routed" means: the WebSocket push was attempted, the Celery SMS task was enqueued, and email was intentionally left as `pending`. Whether Twilio actually delivers the SMS, whether the email is sent tonight, or whether the WebSocket push reached the client — none of that is Kafka's concern. The offset is committed once routing is complete.

> 📝 **Engineering Note — Two independent retry systems:** This document describes two completely separate retry mechanisms that must not be confused:
> - **Kafka replay** — triggered when the alert service fails to *process* the message at all (i.e., the bulk INSERT into PostgreSQL fails). The offset is not committed, so Kafka replays the message on restart. This is a processing-level safety net.
> - **Celery retry** — triggered when a specific *delivery attempt* fails after the message has already been processed (e.g., Twilio is down). The Kafka offset has already been committed at this point. Celery owns these retries entirely; Kafka is no longer involved.
>
> These two systems operate at different layers and are completely independent of each other.

---

## 4. Step 1 — Channel Lookup

The Kafka message contains a `user_id` — the pipeline already determined this user meets the relevance threshold. The alert service only needs to know **what channels** they want for this topic.

```sql
SELECT
    tc.topic_id,
    t.user_id,
    tc.channel
FROM topic_channels tc
JOIN topics t ON tc.topic_id = t.id
WHERE
    t.user_id = :user_id
    AND tc.topic_id = :topic_id
    AND t.is_active = TRUE
```

This returns a flat list of (user_id, channel) pairs. One user with two channels configured appears twice — once per channel.

**Example result:**
```
user_1 | websocket
user_1 | email
```

> 📝 **Engineering Note:** We filter `is_active = TRUE` here as a safety check. A user could deactivate a topic between when the pipeline matched it and when the alert service processes it. This check prevents delivering alerts for topics the user has since paused.

---

## 5. Step 2 — Bulk Alert Insert

All alert rows are inserted in a single PostgreSQL statement — not one INSERT per row.

```sql
INSERT INTO alerts (user_id, article_id, topic_id, relevance_score, channel, status)
VALUES
    ('user_1', :article_id, :topic_id, :relevance_score, 'websocket', 'pending'),
    ('user_1', :article_id, :topic_id, :relevance_score, 'email',     'pending')
ON CONFLICT (user_id, article_id, topic_id, channel) DO NOTHING
```

All rows start with `status = 'pending'`. Delivery handlers update status to `sent` or `failed` after attempting delivery.

**Why bulk INSERT?**
A user can have multiple channels configured. One statement for all channel rows is cleaner than one INSERT per channel — it eliminates unnecessary round trips and keeps the write atomic.

> 📝 **Engineering Note:** PostgreSQL can comfortably handle tens of thousands of writes per second on modest hardware. The concern with individual INSERTs is not write volume — it is the network round trip cost per statement. Bulk INSERT eliminates that overhead entirely.
> **Engineering Note:** ON CONFLICT DO NOTHING makes this INSERT idempotent � if the alert row already exists due to a Kafka replay, the duplicate is silently ignored. A known edge case exists where Celery may dispatch a duplicate SMS if the task was enqueued before a crash and the Kafka message is replayed. This is acceptable for v1 � it requires multiple simultaneous failure conditions and is rare enough not to warrant additional complexity.


---

## 6. Step 3 — Channel Routing

After the bulk INSERT, the alert service iterates through the (user_id, channel) pairs and routes each one:

```python
for user_id, channel, alert_id in delivery_queue:
    if channel == "websocket":
        handle_websocket(user_id, alert_id, article)

    elif channel == "sms":
        dispatch_sms_task.delay(alert_id, user_id)   # Celery async task

    elif channel == "email":
        pass  # intentionally left — Celery Beat handles at midnight UTC
```

Channel handlers are isolated from each other. An exception in SMS dispatch does not interrupt WebSocket delivery for the same user. Each channel's failure is caught and logged independently.

---

## 7. WebSocket Delivery

WebSocket delivery is handled directly in the alert service — no Celery involved.

```python
def handle_websocket(user_id, alert_id, article):
    connection = connection_manager.get(user_id)

    if connection is None:
        # User is offline — alert already persisted as 'pending'
        # User will fetch it via GET /alerts on reconnect
        return

    try:
        connection_manager.push(user_id, {
            "event": "new_alert",
            "data": {
                "id": alert_id,
                "topic_id": topic_id,
                "topic_name": topic_name,
                "headline": article.headline,
                "summary": article.summary,
                "url": article.url,
                "source_name": article.source_name,
                "relevance_score": relevance_score,
                "created_at": created_at
            }
        })

        db.execute(
            "UPDATE alerts SET status='sent', sent_at=NOW() WHERE id=:id",
            {"id": alert_id}
        )

    except WebSocketDisconnect:
        # Connection existed but closed mid-push
        # Leave status as 'pending' — do not retry
        pass
```

**Two offline scenarios handled identically:**

| Scenario | Handling |
|----------|----------|
| User was never connected | `connection_manager.get()` returns None — skip silently |
| User disconnected mid-push | `WebSocketDisconnect` caught — leave as `pending` |

In both cases the alert row stays `pending` in PostgreSQL. When the user opens their dashboard, `GET /alerts` returns all their alerts regardless of status — they see the missed alert in their feed.

**Why no retry for WebSocket?**
Retrying a WebSocket push that just failed makes no sense — the connection is already broken. The REST API (`GET /alerts`) is the natural fallback for offline users. Retrying would add complexity for zero benefit.

---

## 8. SMS Delivery — Celery Task

SMS is dispatched as an immediate Celery task. The alert service does not call Twilio directly — it enqueues a task and moves on.

```python
# Alert service — dispatch only
dispatch_sms_task.delay(alert_id=alert_id, user_id=user_id)
```

```python
# Celery worker — actual delivery
@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60      # base delay in seconds
)
def dispatch_sms_task(self, alert_id: str, user_id: str):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        alert = db.query(Alert).filter(Alert.id == alert_id).first()
        article = db.query(Article).filter(Article.id == alert.article_id).first()

        if not user.phone_number:
            db.execute(
                "UPDATE alerts SET status='failed' WHERE id=:id",
                {"id": alert_id}
            )
            log.error(f"SMS delivery skipped — no phone number for user {user_id}")
            return

        twilio_client.messages.create(
            to=user.phone_number,
            from_=settings.TWILIO_FROM_NUMBER,
            body=f"Alert: {article.headline}\n{article.url}"
        )

        db.execute(
            "UPDATE alerts SET status='sent', sent_at=NOW() WHERE id=:id",
            {"id": alert_id}
        )

    except TwilioException as e:
        if self.request.retries >= self.max_retries:
            # All retries exhausted — mark permanently failed
            db.execute(
                "UPDATE alerts SET status='failed' WHERE id=:id",
                {"id": alert_id}
            )
        # else: leave status as 'pending' — still retrying, not a permanent failure yet
        raise self.retry(exc=e, countdown=self._get_backoff_delay())

def _get_backoff_delay(self):
    # Attempt 1 → immediate
    # Attempt 2 → 60 seconds (1 minute)
    # Attempt 3 → 300 seconds (5 minutes)
    # Attempt 4 → 1800 seconds (30 minutes) → give up, status stays 'failed'
    delays = [0, 60, 300, 1800]
    return delays[min(self.request.retries, len(delays) - 1)]
```

> 📝 **Engineering Note:** The null guard on `user.phone_number` is a last line of defense only. The primary validation happens at `PUT /topics/{id}/channels` — the API rejects SMS channel configuration if `phone_number` is not set. This guard exists because defensive programming requires assuming any layer above can fail or be bypassed (e.g. direct API calls via Postman, data inconsistencies from before the validation was added).

**Why slow backoff for SMS (not 2s/4s/8s like the pipeline)?**
Twilio outages are infrastructure-level failures — they last minutes, not seconds. Retrying after 2 seconds when Twilio is down wastes a retry attempt. Slow backoff (1min → 5min → 30min) gives Twilio time to recover between attempts.

---

## 9. Email Delivery — Celery Beat Digest

Email alerts are never dispatched immediately. They accumulate in the `alerts` table as `pending` rows and are swept up by a scheduled Celery Beat job at midnight UTC every day.

**Celery Beat schedule:**
```python
celery_app.conf.beat_schedule = {
    "send-email-digest": {
        "task": "tasks.send_email_digest",
        "schedule": crontab(hour=0, minute=0),  # midnight UTC daily
    }
}
```

**Digest task:**
```python
@celery_app.task
def send_email_digest():
    # Fetch all unsent email alerts grouped by user
    pending = db.execute("""
        SELECT
            a.user_id,
            u.email,
            u.name,
            array_agg(a.id)             AS alert_ids,
            array_agg(ar.headline)      AS headlines,
            array_agg(ar.summary)       AS summaries,
            array_agg(ar.url)    AS urls,
            array_agg(t.name)           AS topic_names
        FROM alerts a
        JOIN users u        ON a.user_id    = u.id
        JOIN articles ar    ON a.article_id = ar.id
        JOIN topics t       ON a.topic_id   = t.id
        WHERE a.channel = 'email'
          AND a.status  = 'pending'
        GROUP BY a.user_id, u.email, u.name
    """).fetchall()

    for user_digest in pending:
        try:
            send_digest_email(
                to=user_digest.email,
                name=user_digest.name,
                headlines=user_digest.headlines,
                summaries=user_digest.summaries,
                urls=user_digest.urls,
                topic_names=user_digest.topic_names
            )

            # Mark all alerts for this user as sent in one UPDATE
            db.execute("""
                UPDATE alerts
                SET status = 'sent', sent_at = NOW()
                WHERE id = ANY(:alert_ids)
            """, {"alert_ids": user_digest.alert_ids})

        except SMTPException:
            # Leave as pending — will be retried at next midnight run
            # Log error with user_id for monitoring
            pass
```

**Why fixed midnight UTC and not per-user configurable?**
Configurable digest intervals require storing a `digest_interval` preference per user, a per-user last-sent timestamp, and a more complex scheduling query. Fixed midnight means one scheduled job, one query, done. Good enough for v1 — per-user scheduling is a v2 feature.

**What if the midnight job itself fails?**
Alerts remain `pending` in PostgreSQL. The next midnight run picks them up — users receive a slightly delayed digest rather than losing their alerts entirely. No data loss.

> 📝 **Engineering Note:** Celery Beat requires a running beat scheduler process alongside your Celery workers. In Docker this means a separate container running `celery beat`. The workers execute the tasks; Beat only triggers them on schedule. They are separate processes.

---

## 10. Error Handling

### 10.1 Summary Table

| Scenario | Behaviour |
|----------|-----------|
| User offline for WebSocket | Leave alert as `pending` — fetched via `GET /alerts` on reconnect |
| WebSocket push fails mid-send | Catch `WebSocketDisconnect`, leave as `pending`, no retry |
| Twilio API down (SMS) | Celery retries: immediate → 1min → 5min → 30min → mark `failed` |
| SMTP failure (email) | Leave as `pending` — next midnight digest picks it up |
| PostgreSQL write fails (bulk INSERT) | Do NOT commit Kafka offset — message replayed on restart |
| Malformed Kafka message | Log error, COMMIT offset — broken messages must not block the partition |
| Topic deactivated between pipeline and alert service | `is_active = TRUE` filter in channel lookup silently skips it |

### 10.2 The `status` Column — Operational Use

The `status` column (`pending` / `sent` / `failed`) is for **operational monitoring**, not frontend filtering. The dashboard always calls `GET /alerts` without status filters — it returns all alerts regardless of delivery status.

Useful monitoring queries:
```sql
-- SMS failures in the last 24 hours (is Twilio down?)
SELECT COUNT(*) FROM alerts
WHERE channel = 'sms' AND status = 'failed'
AND created_at > NOW() - INTERVAL '24 hours';

-- Pending email alerts ahead of tonight's digest
SELECT COUNT(*), user_id FROM alerts
WHERE channel = 'email' AND status = 'pending'
GROUP BY user_id;

-- WebSocket alerts stuck as pending (users who haven't reconnected)
SELECT COUNT(*) FROM alerts
WHERE channel = 'websocket' AND status = 'pending'
AND created_at < NOW() - INTERVAL '1 hour';
```

---

## 11. Full Flow Diagram

```
Kafka: matched-articles
  { article_id, topic_id, relevance_score, user_id: "u1" }
        ↓
[STEP 1] CHANNEL LOOKUP
  SELECT user_id, channel FROM topic_channels
  WHERE user_id = :user_id AND topic_id = :topic_id AND is_active = TRUE
  → [(u1, websocket), (u1, email)]
        ↓
[STEP 2] FETCH ARTICLE
  SELECT headline, summary, url, source_name FROM articles
  WHERE id = :article_id
        ↓
[STEP 3] BULK INSERT
  INSERT INTO alerts — one row per channel configured by the user
  All rows: status = 'pending'
        ↓
[STEP 4] CHANNEL ROUTING
        ↓               ↓                    ↓
   WEBSOCKET           SMS                 EMAIL
        ↓               ↓                    ↓
ConnectionManager  Celery task          Leave as pending
   .push()         dispatched           Celery Beat picks
        ↓          immediately          up at midnight UTC
  connection?            ↓                    ↓
  yes → push        Twilio API          Batch all pending
  + mark sent       slow backoff        email alerts per
  no → leave        (1m/5m/30m)         user → one email
  as pending        → mark sent         → mark sent
                    or failed
        ↓
COMMIT Kafka offset
```

---

> This document was produced as part of Phase 3 (Low-Level Design).
> Depends on: `schema.sql`, `high-level-design.md`, `api-contracts.md`, `kafka-lld.md`
> Next LLD section: Celery Task Design
