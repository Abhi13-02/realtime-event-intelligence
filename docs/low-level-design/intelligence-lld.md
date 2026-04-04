# Intelligence Layer — Low-Level Design

> **Section:** 3.8 — Sub-theme Discovery & Sentiment Analysis
> **Phase:** 3 — Low-Level Design
> **Depends on:** schema.sql, high-level-design.md, pipeline-lld.md, kafka-lld.md, celery-lld.md

---

## Table of Contents

1. [Overview](#1-overview)
2. [Data Sources in the Intelligence Layer](#2-data-sources-in-the-intelligence-layer)
3. [Discovery Job — Trigger & Inputs](#3-discovery-job--trigger--inputs)
4. [Step 1 — Clustering (GDELT articles only)](#4-step-1--clustering-gdelt-articles-only)
5. [Step 2 — Reddit Assignment (by centroid proximity)](#5-step-2--reddit-assignment-by-centroid-proximity)
6. [Step 3 — Sentiment Analysis](#6-step-3--sentiment-analysis)
7. [Step 4 — LLM Labeling](#7-step-4--llm-labeling)
8. [Step 5 — Evolution Detection](#8-step-5--evolution-detection)
9. [Step 6 — Persist & Publish](#9-step-6--persist--publish)
10. [Environment Variables](#10-environment-variables)
11. [Error Handling](#11-error-handling)
12. [Full Flow Diagram](#12-full-flow-diagram)

---

## 1. Overview

The intelligence layer extends the system from a per-article alert system into a topic intelligence system. Rather than only notifying users when a new article arrives, it detects when the *shape* of a topic is changing — new narrative threads emerging, existing ones growing or fading, public sentiment shifting.

This is implemented as a single **Celery periodic task** (`run_subtheme_discovery`) that runs every 6 hours. It reads from PostgreSQL (no Kafka consumption), performs all computation, persists results, and publishes to the `sub-theme-events` Kafka topic only when a meaningful change is detected.

**Key principles:**
- Source separation: GDELT articles shape sub-themes. Reddit posts + comments measure sentiment. They do not overlap.
- Batch over stream: sub-theme discovery needs a window of history to cluster meaningfully — it cannot operate message-by-message. Celery Beat is the right abstraction; Kafka consumption is not.
- LLM is called sparingly: only when a sub-theme is new or has changed significantly. Not on every run.
- All thresholds are configurable via environment variables. Nothing is hardcoded.

> 📝 **Engineering Note:** This is a fundamentally different computation pattern from the processing pipeline. The pipeline processes one article at a time as they arrive (stream processing). The discovery job processes a window of history for all topics in one scheduled batch (batch processing). These two patterns require different tools — Celery Beat for batch, Kafka consumers for stream. Using a Kafka consumer here would require accumulating state across thousands of messages in memory, knowing when "enough" has arrived, and deciding when to run — none of which Kafka is designed for.

---

## 2. Data Sources in the Intelligence Layer

| Source | Role | How it enters | Used for |
|--------|------|---------------|----------|
| GDELT | Cluster formation | Full pipeline — embed, match, store, summarise, alert | Clustering (embeddings), volume count, representative article |
| Reddit posts | Centroid assignment | Partial pipeline — embed, match, store only. No summarisation. No alert. | Volume count, centroid proximity assignment |
| Reddit comments | Sentiment input | Fetched via PRAW in Step 3 of the discovery job, **after** posts are assigned to centroids. Stored in `reddit_comments` at that point. | VADER sentiment aggregation per sub-theme |

Reddit posts are **never** surfaced to users as alerts. They exist in the database solely as clustering-adjacent content and as carriers of comments.

> 📝 **Engineering Note:** The reason Reddit posts are not used to form clusters is signal quality. A Reddit post title is often a reaction to news ("This is insane", "Thoughts on the new NVIDIA chip?") rather than a description of the event itself. GDELT articles have structured, informative headlines that produce more semantically meaningful embeddings. Clusters formed from GDELT embeddings are cleaner and more coherent. Reddit posts are then assigned to those clusters by proximity — they contribute to volume and carry comments for sentiment, but they don't define what the sub-theme is about.

---

## 3. Discovery Job — Trigger & Inputs

**Trigger:** Celery Beat, every `SUBTHEME_DISCOVERY_INTERVAL_HOURS` hours (default: 6).

**Scope:** All topics where `is_active = TRUE`. Topics are processed independently — a failure on one topic does not block others.

**Rolling window:** `SUBTHEME_WINDOW_DAYS` (default: 3, range 3–5). Only articles crawled within this window are considered for clustering. Articles older than the window are irrelevant to current sub-theme state.

**Minimum article guard:** Before clustering a topic, the job checks whether it has at least `SUBTHEME_MIN_ARTICLES` GDELT articles in the window (default: 5). If not, skip this topic silently — you cannot meaningfully cluster 2 articles.

```python
# Fetch GDELT articles for one topic within the rolling window
gdelt_articles = db.execute("""
    SELECT
        a.id,
        a.embedding,
        a.headline,
        s.type AS source_type
    FROM article_topic_matches atm
    JOIN articles a  ON atm.article_id = a.id
    JOIN sources  s  ON a.source_id    = s.id
    WHERE atm.topic_id  = :topic_id
      AND s.type        = 'gdelt'
      AND a.crawled_at >= NOW() - INTERVAL ':window days'
""", {"topic_id": topic_id, "window": SUBTHEME_WINDOW_DAYS}).fetchall()

if len(gdelt_articles) < SUBTHEME_MIN_ARTICLES:
    log.info(f"Topic {topic_id}: only {len(gdelt_articles)} GDELT articles in window — skipping")
    continue
```

> 📝 **Engineering Note:** The minimum article guard prevents HDBSCAN from running on degenerate input. HDBSCAN requires at least `min_cluster_size` data points. Running it with 2 articles would produce no clusters (everything labelled noise) and waste a Cohere API call on labeling nothing. The guard is a cheap O(1) check before any heavy computation.

---

## 4. Step 1 — Clustering (GDELT articles only)

**Input:** List of GDELT article embeddings (384-dim numpy arrays) for this topic and window
**Output:** Cluster assignments — each article gets a cluster label, or -1 (noise/outlier)

**Algorithm:** HDBSCAN (Hierarchical Density-Based Spatial Clustering of Applications with Noise)

```python
import hdbscan
import numpy as np

embeddings = np.array([a.embedding for a in gdelt_articles])

clusterer = hdbscan.HDBSCAN(
    min_cluster_size=SUBTHEME_MIN_CLUSTER_SIZE,   # default: 3
    min_samples=SUBTHEME_MIN_SAMPLES,             # default: 2
    metric='euclidean'
)
labels = clusterer.fit_predict(embeddings)
# labels[i] = cluster index for gdelt_articles[i], or -1 if noise
```

**Why HDBSCAN and not K-means?**

K-means requires specifying K (the number of clusters) upfront. The number of sub-themes within a topic is unknowable ahead of time — a topic like "AI chips" might have 2 sub-themes in a quiet week and 12 during a major product cycle. HDBSCAN discovers the number of clusters automatically from the density structure of the data. It also handles noise natively (labelling outlier articles as -1) rather than forcing every article into a cluster regardless of whether it belongs.

> 📝 **Engineering Note:** Articles labelled -1 (noise) are not discarded — they are simply not assigned to any sub-theme in the memberships table. They still count toward pipeline processing and are still delivered as article alerts. They just don't contribute to sub-theme intelligence. This is the correct behaviour: a one-off article about a tangential subject should not pollute a coherent sub-theme cluster.

**Computing centroids:**

After clustering, compute the mean embedding vector for each cluster — this becomes the `centroid` stored on the `sub_themes` row.

```python
clusters = {}
for i, label in enumerate(labels):
    if label == -1:
        continue  # noise — skip
    clusters.setdefault(label, []).append(gdelt_articles[i])

sub_theme_data = {}
for label, members in clusters.items():
    member_embeddings = np.array([a.embedding for a in members])
    centroid = member_embeddings.mean(axis=0)

    # Representative article: closest embedding to the centroid
    similarities = [
        cosine_similarity(a.embedding, centroid)
        for a in members
    ]
    representative = members[np.argmax(similarities)]

    # Keywords: top N unique words from member headlines
    keywords = extract_keywords([a.headline for a in members], top_n=10)

    sub_theme_data[label] = {
        "members": members,
        "centroid": centroid,
        "representative_article_id": representative.id,
        "keywords": keywords,
    }
```

> 📝 **Engineering Note:** Storing the centroid in PostgreSQL as a VECTOR(384) column (with a pgvector IVFFlat index) means the Reddit assignment step in Step 2 can use a fast ANN query (`ORDER BY centroid <=> :embedding`) rather than loading all centroids into memory and computing similarity in Python. This becomes important as the number of sub-themes per topic grows.

---

## 5. Step 2 — Reddit Assignment (by centroid proximity)

**Input:** Cluster centroids computed in Step 1, Reddit post embeddings for this topic and window
**Output:** Each Reddit post assigned to its nearest sub-theme (if above similarity threshold)

```python
# Fetch Reddit posts for this topic within the rolling window
reddit_posts = db.execute("""
    SELECT a.id, a.embedding
    FROM article_topic_matches atm
    JOIN articles a ON atm.article_id = a.id
    JOIN sources  s ON a.source_id    = s.id
    WHERE atm.topic_id  = :topic_id
      AND s.type        = 'reddit'
      AND a.crawled_at >= NOW() - INTERVAL ':window days'
""", {"topic_id": topic_id, "window": SUBTHEME_WINDOW_DAYS}).fetchall()
```

For each Reddit post, find the nearest sub-theme centroid using pgvector:

```python
for post in reddit_posts:
    result = db.execute("""
        SELECT id, 1 - (centroid <=> :embedding) AS similarity
        FROM sub_themes
        WHERE topic_id = :topic_id
        ORDER BY centroid <=> :embedding
        LIMIT 1
    """, {"embedding": post.embedding, "topic_id": topic_id}).fetchone()

    if result and result.similarity >= SUBTHEME_REDDIT_ASSIGN_THRESHOLD:
        sub_theme_memberships.append({
            "sub_theme_id": result.id,
            "article_id": post.id,
            "membership_type": "reddit",
            "similarity_to_centroid": result.similarity,
        })
    # else: post is not close enough to any sub-theme — not assigned
```

**Environment variable:**
```
SUBTHEME_REDDIT_ASSIGN_THRESHOLD=0.55   # default
```
Reddit posts below this similarity to the nearest centroid are not assigned to any sub-theme. They remain in the articles table and still carried out their purpose (the topic match already happened in the pipeline). They simply don't contribute to sub-theme intelligence for this run.

> 📝 **Engineering Note:** The assignment threshold exists because GDELT articles that formed a cluster are by definition close to the centroid. Reddit posts are a separate body of content — they may be related to the topic broadly but not necessarily close to any specific sub-theme. Forcing every Reddit post into the nearest cluster regardless of similarity would pollute sub-theme sentiment with loosely related content. The threshold ensures only genuinely relevant Reddit posts influence a sub-theme's sentiment score.

---

## 6. Step 3 — Fetch Comments + Sentiment Analysis

**Input:** Reddit post IDs assigned to each sub-theme (from Step 2)
**Output:** Comments stored in `reddit_comments`, sentiment score and label per sub-theme

This step has two sub-steps: first fetch comments from the Reddit API for assigned posts, then run VADER over those comments.

### 6.1 Fetch Comments via PRAW

Comments are fetched **here**, not at crawl time. Only posts that were actually assigned to a sub-theme centroid in Step 2 have their comments fetched — posts that were not assigned to any sub-theme are ignored entirely.

```python
import praw

reddit = praw.Reddit(
    client_id=os.environ["REDDIT_CLIENT_ID"],
    client_secret=os.environ["REDDIT_CLIENT_SECRET"],
    user_agent="subtheme-discovery/1.0"
)

for sub_theme_id, data in sub_theme_data.items():
    reddit_member_ids = [
        m["article_id"]
        for m in sub_theme_memberships
        if m["sub_theme_id"] == sub_theme_id
        and m["membership_type"] == "reddit"
    ]

    if not reddit_member_ids:
        data["sentiment_score"] = None
        data["sentiment_label"] = None
        continue

    # Fetch Reddit post URLs for these article IDs
    post_urls = db.execute("""
        SELECT id, url FROM articles WHERE id = ANY(:ids)
    """, {"ids": reddit_member_ids}).fetchall()

    all_comments = []

    for post in post_urls:
        try:
            submission = reddit.submission(url=post.url)
            submission.comments.replace_more(limit=0)  # flatten comment tree, no extra API calls
            top_comments = sorted(
                submission.comments.list(),
                key=lambda c: c.score,
                reverse=True
            )[:50]  # top 50 comments by upvote score

            comment_rows = [
                {"article_id": post.id, "body": c.body, "score": c.score}
                for c in top_comments
                if hasattr(c, "body")  # filter out MoreComments objects
            ]
            all_comments.extend(comment_rows)

        except Exception as e:
            # Post may have been deleted or made private since crawl
            log.warning(f"Could not fetch comments for {post.url}: {e}")
            continue

    if not all_comments:
        data["sentiment_score"] = None
        data["sentiment_label"] = None
        continue

    # Persist comments — DELETE existing rows for these articles first to avoid
    # duplicates on re-runs (discovery job runs every 6 hours; a post may be
    # re-assigned to the same sub-theme on the next run)
    db.execute("""
        DELETE FROM reddit_comments WHERE article_id = ANY(:ids)
    """, {"ids": reddit_member_ids})

    db.execute_bulk("""
        INSERT INTO reddit_comments (article_id, body, score) VALUES %s
    """, comment_rows=all_comments)

    data["all_comments"] = all_comments
```

> 📝 **Engineering Note:** Comments are fetched here — after centroid assignment — and not at crawl time for a deliberate cost reason. The `crawl_reddit` task fetches up to 100 posts per run (25 per subreddit × 4 subreddits). Most of these posts will not be assigned to any sub-theme centroid — they matched a topic broadly but don't cluster tightly enough. Fetching comments for all 100 posts at crawl time would be ~100 PRAW API calls per crawl cycle for content that is largely thrown away. Fetching after centroid assignment means we only call the Reddit API for posts that will actually be used for sentiment analysis — typically a small fraction of the crawled set.

> 📝 **Engineering Note:** `replace_more(limit=0)` is important. Reddit's comment tree contains `MoreComments` objects that are placeholders for collapsed threads. Without flattening, iterating `submission.comments.list()` would raise exceptions on those objects. `limit=0` removes all `MoreComments` objects without making additional API calls — we get only the top-level comments already loaded.

### 6.2 Run VADER Sentiment

**Tool:** VADER (Valence Aware Dictionary and Sentiment Reasoner) — runs locally, no API call.

```python
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()

for sub_theme_id, data in sub_theme_data.items():
    comments = data.get("all_comments", [])

    if not comments:
        data["sentiment_score"] = None
        data["sentiment_label"] = None
        continue

    # Weighted VADER: weight each comment's compound score by its upvote score
    # Comments with score <= 0 get a minimum weight of 1 to avoid zero-weight division
    total_weight = 0
    weighted_sum = 0.0
    for comment in comments:
        score = analyzer.polarity_scores(comment["body"])["compound"]
        weight = max(comment["score"], 1)
        weighted_sum += score * weight
        total_weight += weight

    sentiment_score = weighted_sum / total_weight

    if sentiment_score >= 0.05:
        sentiment_label = "positive"
    elif sentiment_score <= -0.05:
        sentiment_label = "negative"
    else:
        sentiment_label = "neutral"

    data["sentiment_score"] = round(sentiment_score, 4)
    data["sentiment_label"] = sentiment_label
```

**Why VADER and not a fine-tuned transformer?**

VADER is a rule-based lexicon model designed specifically for social media text — short, informal, slang-heavy content like Reddit comments. It runs in microseconds per comment with no GPU and no API call. A fine-tuned transformer (e.g. `cardiffnlp/twitter-roberta-base-sentiment`) would be ~100x slower and require a model download. For comment-level sentiment aggregation at our volume, VADER's accuracy is more than sufficient and the latency advantage is significant.

> 📝 **Engineering Note:** Weighting by upvote score is deliberate. Reddit surfaces the most agreed-upon reactions at the top. A comment with 2,000 upvotes represents community consensus; a comment with 1 upvote is one person's opinion. Treating both equally would make sentiment vulnerable to fringe comments. The weighting scheme ensures the sentiment score reflects what the community actually thinks, not a naive average of all voices.

---

## 7. Step 4 — LLM Labeling

**Input:** Keywords, centroid article headlines, volume count, sentiment for each sub-theme
**Output:** Human-readable label and description, stored on the `sub_themes` row

**When to call the LLM:**
1. The sub-theme is **new** (no existing row in `sub_themes` for this topic matches the centroid within `SUBTHEME_CENTROID_MATCH_THRESHOLD`)
2. The sub-theme already exists but its **volume has changed significantly** since the last label was generated (`abs(current_volume - volume_at_last_label) / volume_at_last_label >= SUBTHEME_RELABEL_VOLUME_CHANGE_THRESHOLD`)

In all other cases, the existing label and description are reused — no LLM call.

```python
RELABEL_THRESHOLD = float(os.environ["SUBTHEME_RELABEL_VOLUME_CHANGE_THRESHOLD"])  # default: 0.5

should_relabel = (
    is_new_sub_theme
    or (
        volume_at_last_label is not None
        and abs(current_volume - volume_at_last_label) / max(volume_at_last_label, 1)
        >= RELABEL_THRESHOLD
    )
)
```

**LangChain + Cohere prompt:**

```python
prompt = f"""
You are an analyst identifying emerging themes in news coverage.

Topic: {topic_name}
Sub-theme keywords: {", ".join(keywords)}
Sample headlines:
{chr(10).join(f"- {h}" for h in sample_headlines[:5])}

Article volume: {gdelt_article_count} news articles, {reddit_post_count} Reddit posts
Sentiment: {sentiment_label} (score: {sentiment_score})

Task:
1. Write a short label (3-6 words) for this sub-theme
2. Write a 1-2 sentence description explaining what this sub-theme is about

Return a JSON object with keys "label" and "description".
Return only the JSON. No preamble, no explanation.
"""

response = cohere_client.generate(prompt)
result = json.loads(response.text.strip())
label = result["label"]
description = result["description"]
```

> 📝 **Engineering Note:** The LLM is called ONCE per sub-theme when new or significantly changed — not on every discovery run. At 6-hour intervals with sub-themes evolving slowly, the vast majority of runs reuse the existing label. In practice this means a small number of Cohere calls per day regardless of how many topics or users exist. This is the same "summarise once, reuse everywhere" cost control principle applied to the intelligence layer.

**Matching new clusters to existing sub-themes:**

On each run, HDBSCAN produces new clusters with new centroids. These need to be matched against existing `sub_themes` rows to determine if a cluster is truly new or is a continuation of an existing sub-theme.

```python
# For each new cluster centroid, check if a close existing sub-theme exists
result = db.execute("""
    SELECT id, 1 - (centroid <=> :centroid) AS similarity
    FROM sub_themes
    WHERE topic_id = :topic_id
      AND status  != 'inactive'
    ORDER BY centroid <=> :centroid
    LIMIT 1
""", {"centroid": new_centroid, "topic_id": topic_id}).fetchone()

if result and result.similarity >= SUBTHEME_CENTROID_MATCH_THRESHOLD:
    # Existing sub-theme — update its centroid and last_seen_at
    existing_sub_theme_id = result.id
    is_new_sub_theme = False
else:
    # New sub-theme — INSERT into sub_themes, call LLM
    is_new_sub_theme = True
```

```
SUBTHEME_CENTROID_MATCH_THRESHOLD=0.80   # default
```

A threshold of 0.80 means the new cluster centroid must be at least 80% similar to an existing centroid to be treated as the same sub-theme. Below 0.80 it is treated as a new sub-theme. This threshold controls how sensitive the system is to sub-theme drift — lower values merge more aggressively, higher values create new sub-theme rows more readily.

---

## 8. Step 5 — Evolution Detection

After computing this run's state for each sub-theme, compare against the most recent previous snapshot from `sub_theme_snapshots` to determine what events to fire.

Four detectable events, each controlled by an env var threshold:

### 8.1 Sub-theme Emerging

Fired when a sub-theme is new — no previous snapshot exists.

```python
if previous_snapshot is None:
    events.append({
        "type": "sub_theme_emerging",
        "sub_theme_id": sub_theme_id,
    })
```

No threshold — if it's new, it's emerging by definition.

### 8.2 Sub-theme Growing

Fired when volume has grown significantly compared to the previous snapshot.

```python
GROWING_THRESHOLD = float(os.environ["SUBTHEME_GROWING_THRESHOLD"])  # default: 0.5

if previous_snapshot is not None:
    volume_delta = (current_volume - previous_snapshot.total_volume) / max(previous_snapshot.total_volume, 1)
    if volume_delta >= GROWING_THRESHOLD:
        events.append({"type": "sub_theme_growing", "sub_theme_id": sub_theme_id})
```

A `SUBTHEME_GROWING_THRESHOLD` of 0.5 means the sub-theme must have grown by at least 50% since the last snapshot to trigger a "growing" alert.

### 8.3 Sub-theme Disappearing

Fired when volume has dropped below a fraction of the sub-theme's peak observed volume.

```python
DISAPPEARING_THRESHOLD = float(os.environ["SUBTHEME_DISAPPEARING_THRESHOLD"])  # default: 0.2

peak_volume = db.execute("""
    SELECT MAX(total_volume) FROM sub_theme_snapshots
    WHERE sub_theme_id = :id
""", {"id": sub_theme_id}).scalar()

if peak_volume and current_volume / max(peak_volume, 1) <= DISAPPEARING_THRESHOLD:
    events.append({"type": "sub_theme_disappearing", "sub_theme_id": sub_theme_id})
```

A `SUBTHEME_DISAPPEARING_THRESHOLD` of 0.2 means volume must have dropped to 20% or less of the sub-theme's historical peak before a "disappearing" alert fires.

> 📝 **Engineering Note:** Using peak volume rather than previous-snapshot volume for the disappearing check prevents false positives. A sub-theme that has consistently low volume (e.g. always 3–4 articles) would constantly trigger a "disappearing" event if checked against the prior snapshot. Peak volume anchors the threshold to the sub-theme's established relevance — a sub-theme is only considered "disappearing" if it was once significant and is now fading.

### 8.4 Sentiment Shift

Fired when the current sentiment score has deviated significantly from the rolling baseline.

```python
SENTIMENT_SHIFT_THRESHOLD = float(os.environ["SUBTHEME_SENTIMENT_SHIFT_THRESHOLD"])  # default: 0.2
BASELINE_DAYS = int(os.environ["SUBTHEME_BASELINE_DAYS"])                            # default: 7

baseline = db.execute("""
    SELECT AVG(sentiment_score)
    FROM sub_theme_snapshots
    WHERE sub_theme_id = :id
      AND sentiment_score IS NOT NULL
      AND snapshot_at >= NOW() - INTERVAL ':days days'
""", {"id": sub_theme_id, "days": BASELINE_DAYS}).scalar()

if (
    baseline is not None
    and current_sentiment_score is not None
    and abs(current_sentiment_score - baseline) >= SENTIMENT_SHIFT_THRESHOLD
):
    events.append({"type": "sub_theme_sentiment_shift", "sub_theme_id": sub_theme_id})
```

A `SUBTHEME_SENTIMENT_SHIFT_THRESHOLD` of 0.2 means the current sentiment score must differ from the 7-day baseline by at least 0.2 on the -1.0 to 1.0 VADER scale. This is a meaningful shift — equivalent to moving from neutral (0.0) to clearly positive (0.2) or clearly negative (-0.2).

> 📝 **Engineering Note:** A 7-day baseline (`SUBTHEME_BASELINE_DAYS=7`) means the system builds up to 28 data points (4 runs/day × 7 days) before the baseline is considered stable. Early snapshots will have thin baselines — this is acceptable. Alerts generated with thin baselines may be slightly noisy, but they are still valuable signals. The system improves in precision as history accumulates. No special bootstrapping logic is needed.

---

## 9. Step 6 — Persist & Publish

### 9.1 Write to PostgreSQL

For each sub-theme in this run:

```
1. UPSERT sub_themes row:
   - If new: INSERT with centroid, keywords, representative_article_id,
             label (if LLM called), status = 'emerging'
   - If existing: UPDATE centroid, last_seen_at, status (recomputed),
                  label/description (if relabeled this run)

2. DELETE existing sub_theme_memberships for this topic
   INSERT new memberships (all GDELT + assigned Reddit members)

3. INSERT sub_theme_snapshots row:
   { sub_theme_id, topic_id, gdelt_article_count, reddit_post_count,
     total_volume, sentiment_score, sentiment_label, status }
```

**Status transition logic:**

| Condition | Status written |
|-----------|---------------|
| No previous snapshot | `emerging` |
| Previous snapshot exists, volume >= growing threshold | `active` |
| Volume <= disappearing threshold of peak | `inactive` |
| Between growing and disappearing thresholds | `active` if previously active, `declining` if volume trending down |

> 📝 **Engineering Note:** Sub-theme memberships are fully replaced on every run (delete all, re-insert) because HDBSCAN re-clusters from scratch each time. Article assignments can shift between runs as new articles arrive and change the density structure. Attempting to merge old and new assignments incrementally would be error-prone. The current memberships table reflects "which articles are in which sub-theme right now" — history is captured in snapshots, not memberships.

### 9.2 Fan-out events to users

Each event is published to the `sub-theme-events` Kafka topic. One message per event per user who tracks the topic:

```python
# Fetch all users whose topic triggered this event
users = db.execute("""
    SELECT t.user_id
    FROM topics t
    WHERE t.id = :topic_id AND t.is_active = TRUE
""", {"topic_id": topic_id}).fetchall()

for user in users:
    kafka_producer.publish("sub-theme-events", {
        "event_type": event["type"],
        "sub_theme_id": sub_theme_id,
        "sub_theme_snapshot_id": snapshot_id,
        "topic_id": topic_id,
        "user_id": user.user_id,
    })
```

The Alert Service consumes `sub-theme-events` and handles delivery (WebSocket, email digest, SMS) — identical channel fan-out logic as `matched-articles`.

> 📝 **Engineering Note:** The discovery job publishes to Kafka rather than calling the Alert Service directly, for the same reason the pipeline publishes to `matched-articles` rather than calling the Alert Service directly: decoupling. If the Alert Service is down when the discovery job runs, the events are buffered in Kafka and delivered when it recovers. Direct function calls or HTTP requests would lose events during Alert Service downtime.

---

## 10. Environment Variables

All thresholds and intervals are configurable via environment variables. No value is hardcoded.

| Variable | Default | Description |
|---|---|---|
| `SUBTHEME_DISCOVERY_INTERVAL_HOURS` | `6` | How often the discovery Celery task runs |
| `SUBTHEME_WINDOW_DAYS` | `3` | Rolling window of article history to cluster over (range 3–5) |
| `SUBTHEME_MIN_ARTICLES` | `5` | Minimum GDELT articles in window before clustering is attempted |
| `SUBTHEME_MIN_CLUSTER_SIZE` | `3` | HDBSCAN minimum cluster size — clusters smaller than this are noise |
| `SUBTHEME_MIN_SAMPLES` | `2` | HDBSCAN min_samples — controls how conservative clustering is |
| `SUBTHEME_CENTROID_MATCH_THRESHOLD` | `0.80` | Cosine similarity required to match a new cluster to an existing sub-theme |
| `SUBTHEME_REDDIT_ASSIGN_THRESHOLD` | `0.55` | Minimum cosine similarity for a Reddit post to be assigned to a sub-theme |
| `SUBTHEME_GROWING_THRESHOLD` | `0.5` | Fractional volume growth vs previous snapshot to trigger "growing" event |
| `SUBTHEME_DISAPPEARING_THRESHOLD` | `0.2` | Fraction of peak volume below which "disappearing" event fires |
| `SUBTHEME_SENTIMENT_SHIFT_THRESHOLD` | `0.2` | Absolute VADER score delta vs baseline to trigger "sentiment_shift" event |
| `SUBTHEME_BASELINE_DAYS` | `7` | Days of snapshot history used to compute sentiment baseline |
| `SUBTHEME_RELABEL_VOLUME_CHANGE_THRESHOLD` | `0.5` | Fractional volume change since last label to trigger LLM re-labeling |

---

## 11. Error Handling

### 11.1 Clustering Failure (HDBSCAN)

HDBSCAN runs locally (no external call). Failures indicate degenerate input or OOM.

```
Strategy: catch exception, log topic_id and article count, skip topic
Do not crash the entire task — other topics must continue processing
```

### 11.2 LLM Labeling Failure (Cohere)

```
Strategy: Exponential backoff, max 3 retries (same as pipeline Stage 4)
On permanent failure:
  - Store sub-theme row with label = NULL, description = NULL
  - Set label_generated_at = NULL
  - Continue — a sub-theme with no label is still valid for volume/sentiment tracking
  - The next discovery run will attempt labeling again (is_new check passes since
    label_generated_at IS NULL)
  - Log error with sub_theme_id for monitoring
```

> 📝 **Engineering Note:** An unlabeled sub-theme is still useful. It contributes to volume counts, carries sentiment scores, and can fire evolution alerts. The label is presentational. Blocking the entire sub-theme on a Cohere failure would degrade the intelligence layer far more than showing a "Label pending" state on the frontend.

### 11.3 Kafka Publish Failure

```
Strategy: Retry with backoff (retries=3, retry.backoff.ms=500)
On permanent failure:
  - Snapshot is already written to PostgreSQL — data is not lost
  - Log error with event type and sub_theme_id
  - Alert is not delivered for this run — the next run will re-evaluate
    the sub-theme state and may fire the event again if the condition persists
```

### 11.4 PostgreSQL Write Failure

```
Strategy: Exponential backoff, max 3 retries
On permanent failure: log error, skip this topic, continue with remaining topics
```

### 11.5 Topic with No GDELT Articles

```
Condition: topic has Reddit articles but zero GDELT articles in the window
Strategy: skip topic silently — cannot cluster without GDELT content
Reddit comments for this topic remain in the DB and will contribute
sentiment in a future run once GDELT articles start arriving
```

---

## 12. Full Flow Diagram

```
Celery Beat — every SUBTHEME_DISCOVERY_INTERVAL_HOURS hours
        ↓
run_subtheme_discovery task
        ↓
for each active topic:
        ↓
[GUARD] Fetch GDELT article count for this topic in window
  < SUBTHEME_MIN_ARTICLES → skip topic
  >= SUBTHEME_MIN_ARTICLES → continue
        ↓
[STEP 1] CLUSTERING — GDELT only
  Load GDELT embeddings from PostgreSQL
  → HDBSCAN → cluster labels (-1 = noise, 0..N = sub-themes)
  → compute centroid per cluster (mean of member embeddings)
  → find representative article (closest embedding to centroid)
  → extract keywords from member headlines
        ↓
[STEP 2] REDDIT ASSIGNMENT — centroid proximity
  Load Reddit post embeddings from PostgreSQL
  → pgvector ANN: nearest centroid per post
  → similarity >= SUBTHEME_REDDIT_ASSIGN_THRESHOLD? assign to sub-theme
        ↓
[STEP 3] FETCH COMMENTS + SENTIMENT
  For each sub-theme's assigned Reddit posts:
    → fetch top 50 comments per post via PRAW (Reddit API)
    → bulk INSERT into reddit_comments (DELETE+INSERT to handle re-runs)
    → VADER compound score per comment, weighted by upvote score
    → aggregate to sentiment_score + sentiment_label per sub-theme
  Posts not assigned to any sub-theme: no comment fetch, no API call
        ↓
[STEP 4] LLM LABELING — only when needed
  Match new cluster centroid to existing sub_themes via pgvector
  similarity >= SUBTHEME_CENTROID_MATCH_THRESHOLD → existing sub-theme
  similarity <  SUBTHEME_CENTROID_MATCH_THRESHOLD → new sub-theme
  Call LangChain + Cohere if: new OR volume changed >= RELABEL threshold
        ↓
[STEP 5] EVOLUTION DETECTION
  Fetch previous snapshot from sub_theme_snapshots
  Compare volume → fire sub_theme_emerging / growing / disappearing?
  Compare sentiment vs baseline → fire sub_theme_sentiment_shift?
        ↓
[STEP 6] PERSIST + PUBLISH
  UPSERT sub_themes (centroid, label, status, last_seen_at)
  DELETE + INSERT sub_theme_memberships for this topic
  INSERT sub_theme_snapshots row
  For each event:
    for each user tracking this topic:
      publish to Kafka: sub-theme-events
        ↓
COMMIT — next topic
        ↓
Alert Service consumes sub-theme-events
  → INSERT intelligence_alerts
  → WebSocket push / SMS Celery task / email digest
```

---

> This document was produced as part of Phase 3 (Low-Level Design).
> Depends on: `schema.sql`, `high-level-design.md`, `pipeline-lld.md`, `kafka-lld.md`, `celery-lld.md`
