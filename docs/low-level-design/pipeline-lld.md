# Pipeline - Low-Level Design

> **Section:** 3.4 - Processing Pipeline
> **Phase:** 3 - Low-Level Design
> **Depends on:** schema.sql, high-level-design.md, api-contracts.md, intelligence-lld.md

---

## Table of Contents

1. [Overview](#1-overview)
2. [Startup - Topic Cache](#2-startup---topic-cache)
3. [Input - Kafka Message Contract](#3-input---kafka-message-contract)
4. [Stage 0 - URL Deduplication](#4-stage-0---url-deduplication)
5. [Stage 1 - Preprocessing](#5-stage-1---preprocessing)
6. [Stage 2 - Vector Deduplication](#6-stage-2---vector-deduplication)
7. [Stage 3 - Topic Matching](#7-stage-3---topic-matching)
8. [Stage 4 - Relevance Scoring](#8-stage-4---relevance-scoring)
9. [Stage 5 - Store Article](#9-stage-5---store-article)
10. [Stage 6 - Summarisation](#10-stage-6---summarisation)
11. [Stage 7 - Publish to Kafka](#11-stage-7---publish-to-kafka)
12. [Source-Aware Routing - Reddit vs News](#12-source-aware-routing---reddit-vs-news)
13. [Output - Kafka Message Contract](#13-output---kafka-message-contract)
14. [Error Handling](#14-error-handling)
15. [Full Flow Diagram](#15-full-flow-diagram)
16. [Intelligence Pipeline (Discovery)](#16-intelligence-pipeline-discovery)

---

## 1. Overview

The pipeline consists of two distinct data flows:
1. **Ingestion Pipeline (Stream):** A long-running Kafka consumer that processes articles from `raw-articles`, matches them against user topics, and publishes alerts to `matched-articles`.
2. **Discovery Pipeline (Batch):** A periodic Celery task that clusters history to identify emerging narratives and shifts in sentiment.

This document focuses on the **Ingestion Pipeline**. For details on Discovery, see [intelligence-lld.md](file:///c:/Users/Abhinav%20Dev/OneDrive/Desktop/realtime%202/realtime-topic-intelligence/docs/low-level-design/intelligence-lld.md).

**Key principles (Ingestion):**
- Fail-fast: cheap elimination stages run first, expensive stages last
- Exact duplicate avoidance happens before embedding generation
- Semantic duplicate avoidance happens immediately after embedding generation
- Stateless per article: each article is processed independently
- Store before summarise: embeddings and matches are persisted before the summarisation call so recovery is possible if Stage 6 fails

> ?? **Engineering Note:** The split dedup design is intentional. URL dedup is exact and almost free, so it belongs before Sentence-BERT. Vector dedup is more powerful but requires the embedding, so it runs immediately after preprocessing.

---

## 2. Startup - Topic Cache

Before processing any article, the pipeline loads all active topics, including their parent and subtopic embeddings, into memory.

```python
# On startup & every 5 minutes
topic_cache = {
    topic.id: {
        "name": topic.name,
        "parent_embedding": topic.parent_embedding,
        "subtopic_embeddings": topic.subtopic_embeddings, # List of vectors
        "user_id": topic.user_id,
        "sensitivity": topic.sensitivity,
    }
    for topic in db.get_active_topics()
}
```

Why cache topics in memory:
- Stage 3 compares every article against every active topic and its generated sub-themes
- Fetching topics from PostgreSQL on every article would be unnecessarily slow
- `user_id` and `sensitivity` are cached alongside the embeddings so Stage 7 can publish without extra DB reads

The cache refreshes every 5 minutes. New topics or sub-themes detected by the Discovery job may take up to 5 minutes to affect the matching logic.

---

## 3. Input - Kafka Message Contract

Every `raw-articles` message must conform to this schema:

```json
{
  "url": "https://techcrunch.com/...",
  "headline": "NVIDIA announces H200 chip",
  "content": "Full article text here...",
  "source_id": "<uuid>",
  "published_at": "2026-03-20T09:00:00Z",
  "image_url": "https://..."
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `url` | string | Yes | Used by Stage 0 URL deduplication |
| `headline` | string | Yes | Combined with content in Stage 1 |
| `content` | string | Yes | Raw HTML or plain text from source |
| `source_id` | UUID | Yes | References `sources` table |
| `published_at` | ISO 8601 | No | May be null |
| `image_url` | string | No | URL to representative image |

The message contract is identical for news and Reddit articles.

---

## 4. Stage 0 - URL Deduplication

**Input:** Raw Kafka message URL  
**Output:** Pass or DROP  
**Drop condition:** URL already exists in `articles`

```sql
SELECT 1 FROM articles WHERE url = :url LIMIT 1
```

Outcomes:

| Result | Action |
|--------|--------|
| Not found | Continue to Stage 1 |
| Found, `pipeline_status = 'processed'` | Drop + commit offset |
| Found, `pipeline_status = 'passed_dedup'` and `summary IS NULL` | Resume from Stage 6 |

This stage saves compute by dropping exact replays before any embedding work happens.

---

## 5. Stage 1 - Preprocessing

**Input:** Raw Kafka message  
**Output:** Clean text + 768-dim embedding  
**Drop condition:** None

```text
1. Strip HTML tags from content
2. Truncate content to ~2000 characters
3. Concatenate: headline + ". " + truncated_content
4. Generate embedding with Sentence-BERT
5. Output: { clean_text, embedding }
```

**Model:** `all-mpnet-base-v2`
- 768-dimensional vectors
- Runs locally
- Loaded once at startup and reused for all articles

---

## 6. Stage 2 - Vector Deduplication

**Input:** Article embedding  
**Output:** Pass or DROP  
**Drop condition:** Cosine similarity >= 0.95 against any stored article

```text
1. Query pgvector nearest-neighbour search
2. If similarity >= 0.95:
   -> DROP + commit offset
3. Else:
   -> CONTINUE to Stage 3
```

This stage catches near-identical syndicated or lightly rewritten copies that survived Stage 0 because they use a different URL.

---

## 7. Stage 3 - Topic Matching

**Input:** Article embedding, in-memory topic cache (parent + subtopic embeddings), sensitivity thresholds  
**Output:** List of matched topics or DROP  
**Drop condition:** No topic or sub-theme meets its own sensitivity threshold

```python
for topic_id, topic in topic_cache.items():
    # Compare against parent topic AND all discovered sub-themes
    scores = [cosine_similarity(article_embedding, sub_emb) for sub_emb in topic.subtopic_embeddings]
    scores.append(cosine_similarity(article_embedding, topic.parent_embedding))
    
    similarity = max(scores)
    user_threshold = thresholds.get(topic.sensitivity, 0.65)

    if similarity >= user_threshold:
        matched_topics.append({
            "topic_id": topic_id,
            "similarity": similarity,
            "user_id": topic.user_id,
        })

if not matched_topics:
    # drop article
```

Why Stage 3 uses multi-vector matching:
- A topic is broader than a single embedding; matching against discovered sub-themes (centroids) ensures we catch specific narrative threads that might be semantically distant from the main topic headline.
- Per-topic thresholds ensure only articles wanted by at least one real user survive.
- This avoids paying Stage 6 summarisation cost for articles that no user will ever receive.

---

## 8. Stage 4 - Relevance Scoring

**Input:** `matched_topics` + article  
**Output:** Scored matches with source credibility  
**Drop condition:** None

This stage attaches `credibility_score` from the source row to each matched topic so both semantic relevance and source credibility are stored together.

---

## 9. Stage 5 - Store Article

**Input:** Clean article + embedding + scored matches  
**Output:** `article_id`  
**Drop condition:** None

Writes:
- `articles` row with `pipeline_status = 'passed_dedup'`, including `image_url`.
- one `article_topic_matches` row per scored match (storing `relevance_score` and `credibility_score`).

Why store before summarising:
- Future Stage 2 vector dedup needs the embedding in PostgreSQL.
- Recovery from Stage 6 failure is possible without rerunning Stages 0-5.

---

## 10. Stage 6 - Summarisation

**Input:** `article_id`, clean article text  
**Output:** Summary stored on article, `pipeline_status = 'processed'`  
**Drop condition:** None

The current implementation can bypass the LLM and use the cleaned feed description directly. Once full-article scraping is added, this stage should call the summarisation provider again.

---

## 11. Stage 7 - Publish to Kafka

**Input:** `article_id`, matched topics already threshold-filtered in Stage 3  
**Output:** One `matched-articles` message per matched topic  
**Drop condition:** None

```json
{
  "article_id": "<uuid>",
  "topic_id": "<uuid>",
  "relevance_score": 0.87,
  "user_id": "<uuid>"
}
```

No threshold logic happens here. If an article reaches Stage 7, at least one alert is guaranteed to be published.

---

## 12. Source-Aware Routing - Reddit vs News

After Stage 5, the pipeline checks the source type.

- Reddit: stop after Stage 5. Store only. No summarisation. No publish.
- News source: continue to Stage 6 and Stage 7.

Why Reddit stops early:
- Reddit posts contribute to **Discovery** and **Sentiment** workflows.
- They are not user-facing alert content.
- They are mapped to News clusters in the Intelligence Pipeline for context.
- Summarising and publishing them would waste compute and create incorrect alerts.

---

## 13. Output - Kafka Message Contract

The pipeline publishes to `matched-articles` with this shape:

```json
{
  "article_id": "<uuid>",
  "topic_id": "<uuid>",
  "relevance_score": 0.87,
  "user_id": "<uuid>"
}
```

The Alert Service fetches headline, summary, and source metadata from PostgreSQL using `article_id`.

---

## 14. Error Handling

### 14.1 Summarisation Failure (Stage 6)

If Stage 6 fails permanently:
- Article remains in DB with `pipeline_status = 'passed_dedup'`
- `summary` remains `NULL`
- Article is not published yet
- Consumer commits the offset and startup recovery retries Stage 6 later

Replay path on restart:
- Stage 0 sees the URL already exists
- `pipeline_status = 'passed_dedup'` and `summary IS NULL`
- Pipeline resumes directly at Stage 6
- On success, Stage 7 publishes using stored `article_topic_matches`

### 14.2 PostgreSQL Failure

If storage fails before commit:
- Do not commit Kafka offset
- Let Kafka replay the message on restart

### 14.3 Malformed Kafka Message

If required fields are missing:
- Log the error
- Commit the offset
- Skip the message

### 14.4 Sentence-BERT Failure (Stage 1)

If the embedder fails:
- Log the error
- Do not commit the offset
- Let the process restart and reload the model

---

## 15. Full Flow Diagram

```text
Kafka: raw-articles
        ?
[STAGE 0] URL DEDUPLICATION
  exact URL replay? DROP before embedding
        ?
[STAGE 1] PREPROCESSING
  clean text + generate embedding
        ?
[STAGE 2] VECTOR DEDUPLICATION
  near-duplicate by similarity? DROP
        ?
[STAGE 3] TOPIC MATCHING
  match against parent + subtopics? DROP
        ?
[STAGE 4] RELEVANCE SCORING
        ?
[STAGE 5] STORE ARTICLE
  (includes image_url + matches)
        ?
[SOURCE CHECK]
  Reddit -> DONE
  News -> continue
        ?
[STAGE 6] SUMMARISATION
  (currently bypassed; uses description)
        ?
[STAGE 7] PUBLISH TO matched-articles
        ?
Alert Service
```

---

## 16. Intelligence Pipeline (Discovery)

While the Ingestion Pipeline processes articles as they arrive, the **Discovery Pipeline** runs as a periodic Celery task to identify higher-level patterns.

**Core Steps:**
1. **Clustering:** HDBSCAN on News embeddings to find narratives.
2. **Reddit Assignment:** Mapping social signals to those narratives.
3. **Sentiment:** Weighted VADER analysis on Reddit comments.
4. **Labeling:** AI-generated (Groq/LLM) labels and descriptions for clusters.
5. **Evolution:** Detecting if a narrative is Growing, Emerging, or Fading.

For full technical details, see the [Intelligence LLD](file:///c:/Users/Abhinav%20Dev/OneDrive/Desktop/realtime%202/realtime-topic-intelligence/docs/low-level-design/intelligence-lld.md).

---

> This document was produced as part of Phase 3 (Low-Level Design).
