# Pipeline — Low-Level Design

> **Section:** 3.4 — Processing Pipeline
> **Phase:** 3 — Low-Level Design
> **Depends on:** schema.sql, high-level-design.md, api-contracts.md, intelligence-lld.md

---

## Table of Contents

1. [Overview](#1-overview)
2. [Startup — Topic Cache](#2-startup--topic-cache)
3. [Input — Kafka Message Contract](#3-input--kafka-message-contract)
4. [Stage 0 — Preprocessing](#4-stage-0--preprocessing)
5. [Stage 1 — Deduplication](#5-stage-1--deduplication)
6. [Stage 2 — Topic Matching](#6-stage-2--topic-matching)
7. [Stage 3 — Store Article](#7-stage-3--store-article)
8. [Stage 4 — Summarisation](#8-stage-4--summarisation)
9. [Stage 5 — Publish to Kafka](#9-stage-5-formerly-stage-6--publish-to-kafka)
10. [Source-Aware Routing — Reddit vs GDELT](#10-source-aware-routing--reddit-vs-gdelt)
11. [Output — Kafka Message Contract](#11-output--kafka-message-contract)
12. [Error Handling](#12-error-handling)
13. [Full Flow Diagram](#13-full-flow-diagram)

---

## 1. Overview

The pipeline is a long-running Kafka consumer process. It reads raw articles from the `raw-articles` topic, runs each article through a 6-stage fail-fast pipeline, and publishes matched articles to the `matched-articles` topic for the Alert Service to consume.

**Key principles:**
- Fail-fast: cheap elimination stages run first, expensive stages last
- Stateless per article: each article is processed independently
- Summarise once: the summarization LLM is called once per article, result reused for all matching users
- Store before summarise: articles are persisted before the summarization call so embeddings are available for future deduplication even if summarisation fails

> 📝 **Engineering Note:** This process runs independently of the FastAPI app. It is not triggered by HTTP requests — it runs 24/7 listening to Kafka. If it crashes and restarts, it resumes from its last committed consumer offset. No articles are lost.

---

## 2. Startup — Topic Cache

Before processing any article, the pipeline loads all active topic embeddings from PostgreSQL into memory:

```python
# On startup
topic_cache = {
    topic.id: {
        "embedding": topic.embedding,   # numpy array, 384 dims
        "user_id": topic.user_id,       # needed by Stage 5 to publish user_id to Kafka
        "sensitivity": topic.sensitivity,  # needed by Stage 5 to apply threshold
    }
    for topic in db.query(Topic).filter(Topic.is_active == True).all()
}
```

**Why cache topics in memory?**
Stage 2 (topic matching) compares every article against every active topic. At 10,000 users with up to 10 topics each, that could be up to 100,000 topic embeddings. Fetching from PostgreSQL on every article would be unacceptably slow.

**Cache invalidation:**
The cache is refreshed every 5 minutes via a background thread. This means a newly created topic may take up to 5 minutes to start matching articles — acceptable given the 10-minute crawl interval.

```python
# Background thread — runs every 5 minutes
def refresh_topic_cache():
    while True:
        time.sleep(300)
        global topic_cache
        topic_cache = load_active_topics_from_db()
```

> 📝 **Engineering Note:** In-memory caching of embeddings is a standard pattern in ML-serving systems. The tradeoff is memory usage vs latency. At 384 floats × 4 bytes × 100,000 topics = ~150MB — well within acceptable range for a single process. The cache stores `user_id` and `sensitivity` alongside each embedding so Stage 5 can fan-out to Kafka with zero database round trips — the cache is the single source of truth for all per-topic metadata the pipeline needs.

---

## 3. Input — Kafka Message Contract

The pipeline consumes from the `raw-articles` Kafka topic. Every message must conform to this schema:

```json
{
  "url": "https://techcrunch.com/...",
  "headline": "NVIDIA announces H200 chip",
  "content": "Full article text here...",
  "source_id": "<uuid>",
  "published_at": "2026-03-20T09:00:00Z"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `url` | string | Yes | Unique identifier for deduplication check |
| `headline` | string | Yes | Used in preprocessing |
| `content` | string | Yes | Raw HTML or plain text from source |
| `source_id` | UUID | Yes | References sources table |
| `published_at` | ISO 8601 | No | May be null for sources that don't expose publish time |

The message contract is identical for GDELT and Reddit articles. Reddit comments are **not** included here — they are fetched by the sub-theme discovery job via the Reddit API after Reddit posts have been assigned to cluster centroids. Only posts that are actually relevant to a sub-theme have their comments fetched. See `intelligence-lld.md` Section 6.

**Consumer configuration:**
```
group.id = pipeline-consumer-group
auto.offset.reset = earliest
enable.auto.commit = false
max.poll.records = 10
```

> 📝 **Engineering Note:** `enable.auto.commit = false` means the pipeline manually commits its offset only after successfully processing each article. If the process crashes mid-article, Kafka replays that article on restart. This guarantees at-least-once processing — every article is processed at least once, though rarely twice.

---

## 4. Stage 0 — Preprocessing

**Input:** Raw Kafka message
**Output:** Clean text + 384-dim embedding
**Drop condition:** None — all articles proceed

```
1. Strip HTML tags from content field
2. Truncate to 512 tokens (Sentence-BERT input limit)
3. Concatenate: text_to_embed = headline + ". " + content[:512]
4. Generate embedding: embedding = sbert_model.encode(text_to_embed)
5. Output: { clean_text, embedding }
```

**Model:** `all-MiniLM-L6-v2` (Sentence-BERT)
- 384-dimensional output vectors
- Runs locally — no API call, no latency, no cost
- Loaded once at process startup, kept in memory

> 📝 **Engineering Note:** We concatenate headline + content (some sentences) before embedding because the headline alone is often too short to produce a meaningful vector. "NVIDIA H200" as a standalone embedding is less informative than the full article context. The period separator prevents the model treating them as one run-on sentence.

---

## 5. Stage 1 — Deduplication

**Input:** Article embedding
**Output:** Pass or DROP
**Drop condition:** Cosine similarity >= 0.95 against any stored article

```
1. Query pgvector ANN index:
   SELECT id FROM articles
   ORDER BY embedding <=> :query_embedding
   LIMIT 1

2. If result exists AND similarity >= 0.95:
   → COMMIT Kafka offset
   → DROP article (do not process further)

3. If no result OR similarity < 0.95:
   → CONTINUE to Stage 2
```

**Why 0.95 threshold?**
A score of 0.95 or above indicates near-identical content — same article reposted by a different outlet or minor edits to the same story. Below 0.95, the content is different enough to be worth processing.

**URL check first (fast path):**
Before running the embedding similarity query, check if the URL already exists:

```sql
SELECT id, pipeline_status, summary FROM articles WHERE url = :url LIMIT 1
```

Three outcomes:

| Result | Action |
|--------|--------|
| Not found | CONTINUE to ANN similarity check |
| Found, `pipeline_status = 'processed'` | DROP + COMMIT offset — article fully processed already |
| Found, `pipeline_status = 'passed_dedup'` AND `summary IS NULL` | **RESUME from Stage 4** — article stored and matched but summarisation failed previously |

The resume path skips Stages 0–3 entirely (already done) and jumps straight to Stage 4 with the `article_id` and stored `headline`/`content` from the DB. Stage 5 then reads matched topics from `article_topic_matches` (already written at Stage 3) instead of from the in-memory result of Stage 2.

> 📝 **Engineering Note:** pgvector's IVFFlat index (`idx_articles_embedding`) makes this ANN search fast even as the articles table grows. It trades a small accuracy loss for significant speed gains — acceptable here since we have the 0.95 threshold as a hard filter anyway. The smarter URL check is what makes "DO NOT commit on summarisation failure" actually useful — without it, a replay would always hit the "URL exists" branch and drop the article before reaching Stage 4.

---

## 6. Stage 2 — Topic Matching

**Input:** Article embedding, in-memory topic cache, sensitivity thresholds (from config)
**Output:** List of matched topics (topic_id, similarity, user_id), or DROP
**Drop condition:** No topic's sensitivity threshold is met

```python
for topic_id, topic in topic_cache.items():
    similarity = cosine_similarity(article_embedding, topic.embedding)
    user_threshold = thresholds[topic.sensitivity]  # from config, e.g. broad=0.55

    if similarity >= user_threshold:
        matched_topics.append({
            "topic_id": topic_id,
            "similarity": similarity,
            "user_id": topic.user_id,
        })

if len(matched_topics) == 0:
    → COMMIT Kafka offset
    → DROP article

if len(matched_topics) > 0:
    → CONTINUE to Stage 3 with matched_topics
```

**Why filter per-topic sensitivity here instead of a fixed floor?**
Each topic belongs to exactly one user with a specific sensitivity preference. Applying the user's own threshold in Stage 2 means an article only proceeds if at least one real user actually wants it. A fixed floor (e.g. 0.55) would pass articles that no `balanced` or `high` user cares about, wasting a DB write and an LLM call. Filtering here guarantees: if an article reaches Stage 3, at least one user will receive an alert for it.

**Thresholds are configurable via env vars:**
```
THRESHOLD_BROAD=0.55
THRESHOLD_BALANCED=0.65
THRESHOLD_HIGH=0.75
```
Change and restart `pipeline-consumer` to take effect. No code changes needed.

> 📝 **Engineering Note:** This is the most important filtering stage by volume. In practice, the majority of crawled articles will not match any tracked topic and get dropped here. This is what makes the summarization call at Stage 4 affordable — by Stage 4 you're down to a small fraction of the original articles. Moving the threshold check here (instead of Stage 6) eliminates the case where an article passes Stage 2, consumes an LLM call, and then gets dropped for every user at Stage 6 — wasted compute.

---

## 7. Stage 3 — Store Article

**Input:** Clean article + embedding + matched_topics
**Output:** article_id (UUID assigned by PostgreSQL)
**Drop condition:** None

```
1. INSERT into articles:
   {
     source_id,
     url,
     headline,
     content,
     embedding,
     pipeline_status = 'passed_dedup',
     summary = NULL,        ← not yet generated
     published_at,
     crawled_at = NOW()
   }

2. INSERT into article_topic_matches for each matched topic:
   {
     article_id,
     topic_id,
     relevance_score,      ← match["similarity"]
     credibility_score     ← match["credibility_score"]
   }

3. Return article_id for use in subsequent stages
```

**Why store before summarising?**
Two reasons:
1. The embedding must exist in PostgreSQL before the next article arrives — otherwise deduplication in Stage 1 cannot compare against it
2. If the summarization call in Stage 4 fails, the article and its matches are already persisted. Stage 4 can be retried without reprocessing the entire pipeline

> 📝 **Engineering Note:** This is the "write-ahead" pattern. Persist first, then perform expensive external operations. If the external call fails, you have a recovery path. If you persisted after summarisation, a provider failure would mean the article is lost entirely.

> 📝 **Engineering Note:** Reddit comments are **not** stored here. Comments are fetched by the sub-theme discovery job via the Reddit API, but only for posts that have already been assigned to a cluster centroid. Fetching comments for every crawled Reddit post at ingestion time would be wasteful — most posts are never assigned to any sub-theme. Deferring comment fetching to the discovery job means we only call the Reddit API for comments that will actually be used for sentiment analysis. See `intelligence-lld.md` Section 6.

---

## 8. Stage 4 — Summarisation

**Input:** article_id, clean article text
**Output:** Summary stored on article, pipeline_status updated
**Drop condition:** None — retry on failure (see Error Handling)

```
prompt = f"""
You are a news summarisation assistant.

Article title: {headline}
Article content: {content}

Task: Write a 2-3 sentence neutral summary of this article.
Return only the summary. No preamble, no labels.
"""

response = summarization_client.generate_content(prompt)
summary = response.text.strip()

UPDATE articles SET
    summary = :summary,
    pipeline_status = 'processed'
WHERE id = :article_id
```

**Cost control:**
- The summarization LLM is called ONCE per article regardless of how many users match it
- The summary is stored in PostgreSQL and served to all matching users from there
- At ~50-100 articles per cycle with most dropped before Stage 4, expect ~10-15 summarization calls per 10-minute cycle

**Current implementation:** Cohere Command R via the LangChain adapter

> 📝 **Engineering Note:** The summary is written to the articles table, not the alerts table. This is intentional — it is a property of the article, not of any individual user's alert. If 200 users receive an alert about the same article, they all read the same summary from one row in the articles table. This is the core cost control mechanism.

---

## 9. Stage 5 (formerly Stage 6) — Publish to Kafka

**Input:** article_id, matched_topics (already threshold-filtered in Stage 2)
**Output:** One `matched-articles` Kafka message per matched topic
**Drop condition:** None — every match here is guaranteed to meet its user's threshold

```python
for match in matched_topics:
    publish_to_kafka("matched-articles", {
        "article_id": article_id,
        "topic_id": match["topic_id"],
        "relevance_score": match["similarity"],
        "user_id": match["user_id"],
    })
```

No threshold logic here — that already happened in Stage 2. This stage's only job is delivery.

> 📝 **Engineering Note:** Each topic belongs to exactly one user — `topic_id` uniquely identifies both the topic and its owner. Fan-out across multiple users happens because multiple different topics (owned by different users) can match the same article. The pipeline publishes one Kafka message per matched topic, each carrying a single `user_id`. The Alert Service fans out per channel, not per user.
>
> Threshold filtering was moved from this stage to Stage 2. This eliminates the worst case: an article passing Stage 2, consuming an LLM call at Stage 4, and then being dropped here for every user. Now if an article reaches this stage, at least one alert is guaranteed to be published.

---

## 10. Source-Aware Routing — Reddit vs GDELT

After Stage 3, the pipeline checks the source type of the article. This is the only point where source type influences pipeline behaviour.

```python
REDDIT_SOURCE_ID = "a1b2c3d4-0006-0006-0006-000000000006"  # hardcoded constant from seed data

if message["source_id"] == REDDIT_SOURCE_ID:
    # Reddit article — stored and matched. Job done.
    # No summarisation. No Kafka publish. No user alert.
    consumer.commit()
    continue  # move to next Kafka message
else:
    # GDELT article — continue to Stage 4 (summarisation) and Stage 5 (publish)
    pass
```

**Why Reddit articles stop here:**

Reddit posts are not alert-generating content. Their purpose in the system is:
1. To be stored with their embeddings so the sub-theme discovery job can assign them to sub-theme clusters by centroid proximity
2. To carry their comments into `reddit_comments` for sentiment analysis

Summarising a Reddit post title with LangChain + Cohere would waste an API call on content that is never shown to users. Publishing to `matched-articles` would cause the Alert Service to generate alerts for Reddit posts — incorrect behaviour.

> 📝 **Engineering Note:** The source check uses the hardcoded `source_id` constant rather than querying the `sources` table for `type = 'reddit'`. This is the same pattern used in the ingestion tasks (Section 3.5 of celery-lld.md) — source_id values are stable constants after first deployment, so querying the DB for them on every article is unnecessary overhead. The constant is defined once at module level and imported wherever needed.

---

## 11. Output — Kafka Message Contract

The pipeline publishes to the `matched-articles` Kafka topic. Every message conforms to this schema:

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
| `article_id` | UUID | References articles table — Alert Service fetches full article from DB |
| `topic_id` | UUID | References topics table |
| `relevance_score` | float | Cosine similarity score for this (article, topic) pair |
| `user_id` | UUID | The user who owns this topic and will receive the alert |

**Why not include the full article in the message?**
The Alert Service needs headline, summary, url, and source_name to build the alert payload. These are already in PostgreSQL. Duplicating them in the Kafka message would increase message size and create data consistency risk if the article is updated after the message is published.

---

## 12. Error Handling

### 11.1 Summarisation Provider Failure (Stage 4)

The summarization provider is the main external dependency in the pipeline stage flow. It must be treated as unreliable.

```
Strategy: Exponential backoff with max 3 retries

Attempt 1: immediate
Attempt 2: wait 2 seconds
Attempt 3: wait 4 seconds
Attempt 4: wait 8 seconds → FAIL

On permanent failure:
- Article remains in DB with pipeline_status = 'passed_dedup'
- summary remains NULL
- Article is NOT published to matched-articles
- Log error with article_id for manual inspection
- DO NOT commit Kafka offset → Stage 1 will resume from Stage 4 on restart

Replay path (on restart):
  Stage 1 URL check: URL exists + pipeline_status = 'passed_dedup' + summary IS NULL
  → fetch article_id, headline, content from articles table
  → skip Stages 0–3 (already completed)
  → go to Stage 4: call the summarization provider with stored headline + content
  → on success: UPDATE summary + pipeline_status = 'processed'
  → Stage 5: query article_topic_matches WHERE article_id = :article_id
             to recover matched topics + relevance scores (already stored at Stage 3)
  → publish to matched-articles as normal
```

> 📝 **Engineering Note:** Articles stuck at `pipeline_status = 'passed_dedup'` with `summary = NULL` are a useful monitoring signal. A dashboard query counting these rows tells you immediately if the summarization provider has been failing. The "DO NOT commit" decision ensures no article is permanently left without a summary as long as the provider recovers — the next restart will always retry Stage 4 for any stuck article.

### 11.2 PostgreSQL Failure (Stages 3, 5)

```
Strategy: Exponential backoff with max 3 retries
On permanent failure: DO NOT commit Kafka offset → replay on restart
```

### 11.3 Malformed Kafka Message

```
If message is missing required fields:
- Log error with raw message content
- COMMIT offset (do not replay — the message is permanently broken)
- Continue to next message
```

### 11.4 Sentence-BERT Failure (Stage 0)

Sentence-BERT runs locally. Failures here indicate a process-level problem (out of memory, corrupted model file).

```
Strategy: Log error, DO NOT commit offset, let process crash and restart
Restart will reload the model from disk
```

---

## 13. Full Flow Diagram

```
Kafka: raw-articles  (GDELT or Reddit message)
        ↓
[STARTUP] Load all active topic embeddings into memory cache
        ↓
[STAGE 0] PREPROCESSING
  Strip HTML → truncate → concatenate headline + content
  → Sentence-BERT → 384-dim embedding
  (embedding uses post body only — comments field ignored here)
        ↓
[STAGE 1] DEDUPLICATION
  URL check (fast path) → if exists: DROP + commit offset
  pgvector ANN search → cosine similarity
  if similarity >= 0.95: DROP + commit offset
        ↓
[STAGE 2] TOPIC MATCHING
  Compare embedding vs all topic embeddings in memory cache
  Apply each topic's own sensitivity threshold (broad/balanced/high from config)
  if similarity >= user_threshold for at least one topic: matched_topics[]
  if no matches: DROP + commit offset
        ↓
[STAGE 3] STORE ARTICLE
  INSERT into articles (pipeline_status = 'passed_dedup', summary = NULL)
  INSERT into article_topic_matches (relevance_score, credibility_score)
  → article_id
  (reddit_comments populated later by discovery job, not here)
        ↓
[SOURCE CHECK] Is source Reddit?
  YES → COMMIT Kafka offset → DONE (no summarisation, no alert)
  NO  → continue to Stage 4
        ↓
[STAGE 4] SUMMARISATION  (GDELT only)
  One LangChain + Cohere call → 2-3 sentence summary
  UPDATE articles SET summary, pipeline_status = 'processed'
  Retry with exponential backoff on failure (max 3 retries)
        ↓
[STAGE 5] PUBLISH  (GDELT only)
  For each matched topic (already threshold-filtered in Stage 2):
    publish to Kafka matched-articles (article_id, topic_id, relevance_score, user_id)
        ↓
COMMIT Kafka offset
        ↓
Kafka: matched-articles → Alert Service
```

---

> This document was produced as part of Phase 3 (Low-Level Design).
> Depends on: `schema.sql`, `high-level-design.md`, `intelligence-lld.md`
> Next LLD section: Kafka Configuration
