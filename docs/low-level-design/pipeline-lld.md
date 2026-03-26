# Pipeline — Low-Level Design

> **Section:** 3.4 — Processing Pipeline
> **Phase:** 3 — Low-Level Design
> **Depends on:** schema.sql, high-level-design.md, api-contracts.md

---

## Table of Contents

1. [Overview](#1-overview)
2. [Startup — Topic Cache](#2-startup--topic-cache)
3. [Input — Kafka Message Contract](#3-input--kafka-message-contract)
4. [Stage 0 — Preprocessing](#4-stage-0--preprocessing)
5. [Stage 1 — Deduplication](#5-stage-1--deduplication)
6. [Stage 2 — Topic Matching](#6-stage-2--topic-matching)
7. [Stage 3 — Relevance Scoring](#7-stage-3--relevance-scoring)
8. [Stage 4 — Store Article](#8-stage-4--store-article)
9. [Stage 5 — Summarisation](#9-stage-5--summarisation)
10. [Stage 6 — User Threshold Filter](#10-stage-6--user-threshold-filter)
11. [Output — Kafka Message Contract](#11-output--kafka-message-contract)
12. [Error Handling](#12-error-handling)
13. [Full Flow Diagram](#13-full-flow-diagram)

---

## 1. Overview

The pipeline is a long-running Kafka consumer process. It reads raw articles from the `raw-articles` topic, runs each article through a 6-stage fail-fast pipeline, and publishes matched articles to the `matched-articles` topic for the Alert Service to consume.

**Key principles:**
- Fail-fast: cheap elimination stages run first, expensive stages last
- Stateless per article: each article is processed independently
- Summarise once: Gemini is called once per article, result reused for all matching users
- Store before summarise: articles are persisted before the Gemini call so embeddings are available for future deduplication even if summarisation fails

> 📝 **Engineering Note:** This process runs independently of the FastAPI app. It is not triggered by HTTP requests — it runs 24/7 listening to Kafka. If it crashes and restarts, it resumes from its last committed consumer offset. No articles are lost.

---

## 2. Startup — Topic Cache

Before processing any article, the pipeline loads all active topic embeddings from PostgreSQL into memory:

```python
# On startup
topic_cache = {
    topic.id: {
        "embedding": topic.embedding,   # numpy array, 384 dims
        "name": topic.name,
        "threshold": topic.threshold
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

> 📝 **Engineering Note:** In-memory caching of embeddings is a standard pattern in ML-serving systems. The tradeoff is memory usage vs latency. At 384 floats × 4 bytes × 100,000 topics = ~150MB — well within acceptable range for a single process.

---

## 3. Input — Kafka Message Contract

The pipeline consumes from the `raw-articles` Kafka topic. Every message must conform to this schema:

```json
{
  "url": "https://techcrunch.com/...",
  "title": "NVIDIA announces H200 chip",
  "content": "Full article text here...",
  "source_id": "<uuid>",
  "published_at": "2026-03-20T09:00:00Z"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `url` | string | Yes | Unique identifier for deduplication check |
| `title` | string | Yes | Used in preprocessing |
| `content` | string | Yes | Raw HTML or plain text from source |
| `source_id` | UUID | Yes | References sources table |
| `published_at` | ISO 8601 | No | May be null for sources that don't expose publish time |

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
3. Concatenate: text_to_embed = title + ". " + content[:512]
4. Generate embedding: embedding = sbert_model.encode(text_to_embed)
5. Output: { clean_text, embedding }
```

**Model:** `all-MiniLM-L6-v2` (Sentence-BERT)
- 384-dimensional output vectors
- Runs locally — no API call, no latency, no cost
- Loaded once at process startup, kept in memory

> 📝 **Engineering Note:** We concatenate title + content before embedding because the title alone is often too short to produce a meaningful vector. "NVIDIA H200" as a standalone embedding is less informative than the full article context. The period separator prevents the model treating them as one run-on sentence.

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
SELECT id FROM articles WHERE url = :url LIMIT 1
```

If URL exists → DROP immediately without any embedding computation. This is cheaper than the vector search and catches exact reposts instantly.

> 📝 **Engineering Note:** pgvector's IVFFlat index (`idx_articles_embedding`) makes this ANN search fast even as the articles table grows. It trades a small accuracy loss for significant speed gains — acceptable here since we have the 0.95 threshold as a hard filter anyway.

---

## 6. Stage 2 — Topic Matching

**Input:** Article embedding, in-memory topic cache
**Output:** List of matched topic IDs, or DROP
**Drop condition:** No topics match

```
matched_topics = []

for topic_id, topic in topic_cache.items():
    similarity = cosine_similarity(article_embedding, topic["embedding"])
    if similarity >= 0.65:
        matched_topics.append({
            "topic_id": topic_id,
            "similarity": similarity
        })

if len(matched_topics) == 0:
    → COMMIT Kafka offset
    → DROP article

if len(matched_topics) > 0:
    → CONTINUE to Stage 3 with matched_topics
```

**Why 0.65 threshold?**
Lower than deduplication (0.95) because topic matching is about semantic relevance, not identity. An article about "NVIDIA GPU supply chain" should match a topic called "AI chips" even though the wording is different. 0.65 captures topical relevance while filtering clearly unrelated content.

> 📝 **Engineering Note:** This is the most important filtering stage by volume. In practice, the majority of crawled articles (sports, politics, entertainment) will not match any tracked tech/research topics and get dropped here. This is what makes the Gemini call at Stage 5 affordable — by Stage 5 you're down to a small fraction of the original articles.

---

## 7. Stage 3 — Relevance Scoring

**Input:** Article embedding, matched topics from Stage 2
**Output:** Scored (article, topic) pairs
**Drop condition:** None

```
scored_matches = []

for match in matched_topics:
    relevance_score = match["similarity"]
    scored_matches.append({
        "topic_id": match["topic_id"],
        "relevance_score": relevance_score,
        "credibility_score": get_source_credibility(article.source_id)
    })
```

**Note:** relevance_score reuses the similarity already computed in Stage 2. No additional computation needed — just store the value.

**credibility_score** is copied from the sources table at match time and stored in article_topic_matches for transparency. It does not affect alerting logic — threshold checks compare only against relevance_score.

---

## 8. Stage 4 — Store Article

**Input:** Clean article + embedding + scored_matches
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

2. INSERT into article_topic_matches for each scored match:
   {
     article_id,
     topic_id,
     relevance_score,
     credibility_score
   }

3. Return article_id for use in subsequent stages
```

**Why store before summarising?**
Two reasons:
1. The embedding must exist in PostgreSQL before the next article arrives — otherwise deduplication in Stage 1 cannot compare against it
2. If the Gemini API call in Stage 5 fails, the article and its matches are already persisted. Stage 5 can be retried without reprocessing the entire pipeline

> 📝 **Engineering Note:** This is the "write-ahead" pattern. Persist first, then perform expensive external operations. If the external call fails, you have a recovery path. If you persisted after Gemini, a Gemini failure would mean the article is lost entirely.

---

## 9. Stage 5 — Summarisation

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

response = gemini_client.generate_content(prompt)
summary = response.text.strip()

UPDATE articles SET
    summary = :summary,
    pipeline_status = 'processed'
WHERE id = :article_id
```

**Cost control:**
- Gemini is called ONCE per article regardless of how many users match it
- The summary is stored in PostgreSQL and served to all matching users from there
- At ~50-100 articles per cycle with most dropped before Stage 5, expect ~10-15 Gemini calls per 10-minute cycle

**Model:** Gemini 1.5 Flash (free tier sufficient for this call volume)

> 📝 **Engineering Note:** The summary is written to the articles table, not the alerts table. This is intentional — it is a property of the article, not of any individual user's alert. If 200 users receive an alert about the same article, they all read the same summary from one row in the articles table. This is the core cost control mechanism.

---

## 10. Stage 6 — User Threshold Filter

**Input:** article_id, scored_matches, topic_cache
**Output:** Publish to `matched-articles` Kafka topic
**Drop condition:** None — this is routing, not filtering

```
for match in scored_matches:
    topic_id = match["topic_id"]
    relevance_score = match["relevance_score"]
    topic_threshold = topic_cache[topic_id]["threshold"]

    # Find all users tracking this topic whose threshold is met
    users = db.query(User).join(Topic).filter(
        Topic.id == topic_id,
        Topic.is_active == True,
        relevance_score >= topic_threshold
    ).all()

    if len(users) == 0:
        continue   # no users meet threshold for this topic

    # Publish one message per topic match (not per user)
    # Alert Service handles fan-out to individual users
    publish_to_kafka("matched-articles", {
        "article_id": article_id,
        "topic_id": topic_id,
        "relevance_score": relevance_score,
        "user_ids": [u.id for u in users]
    })
```

> 📝 **Engineering Note:** We publish one message per (article, topic) pair — not one message per user. The Alert Service receives this message and fans out to individual users. This keeps the matched-articles topic clean and avoids publishing thousands of near-identical messages when many users track the same topic.

---

## 11. Output — Kafka Message Contract

The pipeline publishes to the `matched-articles` Kafka topic. Every message conforms to this schema:

```json
{
  "article_id": "<uuid>",
  "topic_id": "<uuid>",
  "relevance_score": 0.87,
  "user_ids": ["<uuid>", "<uuid>", "..."]
}
```

| Field | Type | Notes |
|-------|------|-------|
| `article_id` | UUID | References articles table — Alert Service fetches full article from DB |
| `topic_id` | UUID | References topics table |
| `relevance_score` | float | Cosine similarity score for this (article, topic) pair |
| `user_ids` | UUID[] | Users whose threshold was met for this topic |

**Why not include the full article in the message?**
The Alert Service needs headline, summary, source_url, and source_name to build the alert payload. These are already in PostgreSQL. Duplicating them in the Kafka message would increase message size and create data consistency risk if the article is updated after the message is published.

---

## 12. Error Handling

### 12.1 Gemini API Failure (Stage 5)

Gemini is the only external API in the pipeline. It must be treated as unreliable.

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
- DO NOT commit Kafka offset → article will be reprocessed on restart
```

> 📝 **Engineering Note:** Articles stuck at `pipeline_status = 'passed_dedup'` with `summary = NULL` are a useful monitoring signal. A dashboard query counting these rows tells you immediately if Gemini has been failing.

### 12.2 PostgreSQL Failure (Stages 4, 6)

```
Strategy: Exponential backoff with max 3 retries
On permanent failure: DO NOT commit Kafka offset → replay on restart
```

### 12.3 Malformed Kafka Message

```
If message is missing required fields:
- Log error with raw message content
- COMMIT offset (do not replay — the message is permanently broken)
- Continue to next message
```

### 12.4 Sentence-BERT Failure (Stage 0)

Sentence-BERT runs locally. Failures here indicate a process-level problem (out of memory, corrupted model file).

```
Strategy: Log error, DO NOT commit offset, let process crash and restart
Restart will reload the model from disk
```

---

## 13. Full Flow Diagram

```
Kafka: raw-articles
        ↓
[STARTUP] Load all active topic embeddings into memory cache
        ↓
[STAGE 0] PREPROCESSING
  Strip HTML → truncate → concatenate title + content
  → Sentence-BERT → 384-dim embedding
        ↓
[STAGE 1] DEDUPLICATION
  URL check (fast path) → if exists: DROP + commit offset
  pgvector ANN search → cosine similarity
  if similarity >= 0.95: DROP + commit offset
        ↓
[STAGE 2] TOPIC MATCHING
  Compare embedding vs all topic embeddings in memory cache
  if similarity >= 0.65 for at least one topic: matched_topics[]
  if no matches: DROP + commit offset
        ↓
[STAGE 3] RELEVANCE SCORING
  cosine_similarity(article, topic) per matched topic
  copy credibility_score from sources table
  → scored_matches[]
        ↓
[STAGE 4] STORE ARTICLE
  INSERT into articles (pipeline_status = 'passed_dedup', summary = NULL)
  INSERT into article_topic_matches
  → article_id
        ↓
[STAGE 5] SUMMARISATION
  One Gemini API call → 2-3 sentence summary
  UPDATE articles SET summary, pipeline_status = 'processed'
  Retry with exponential backoff on failure (max 3 retries)
        ↓
[STAGE 6] USER THRESHOLD FILTER
  For each matched topic:
    Query users where relevance_score >= user.threshold
    Publish to Kafka matched-articles (one message per topic match)
        ↓
COMMIT Kafka offset
        ↓
Kafka: matched-articles → Alert Service
```

---

> This document was produced as part of Phase 3 (Low-Level Design).
> Depends on: `schema.sql`, `high-level-design.md`
> Next LLD section: Kafka Configuration
