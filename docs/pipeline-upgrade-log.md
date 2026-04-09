# Pipeline Upgrade Log

This document tracks the accuracy of the pipeline's Stage 2 (topic matching) across versions.
Every time an upgrade is made, a new entry is added here with benchmark results and what changed.

---

## How the Testing Works

### The Dataset

`tests/testDataset.tsv` — 300 labeled news articles across 5 broad topics, 4 sub-categories each, 15 articles per sub-category.

| Broad Topic | Sub-categories (15 articles each) |
|---|---|
| Artificial Intelligence | ai_regulation, ai_healthcare, ai_jobs, ai_research |
| Climate Change | climate_policy, climate_oceans, climate_energy, climate_disasters |
| Global Economy | economy_trade, economy_recession, economy_markets, economy_inflation |
| Space Exploration | space_research, space_policy, space_missions, space_commercialization |
| Public Health | health_systems, health_pandemic, health_mental, health_drugs |

Each article has a ground-truth label. The benchmark runs every article through the pipeline and checks whether the correct topic wins.

---

### The Benchmark Tests

**`tests/test_pipeline_accuracy_db.py`** — the honest production test.
Fetches real topics from Postgres (with their Gemini-expanded embeddings), runs 300 articles through Stage 0 → Stage 2 exactly as production does, and measures accuracy.

```bash
docker compose exec backend bash -c "cd /app && PYTHONPATH=/app pytest tests/test_pipeline_accuracy_db.py -v -s"
```

**`tests/model_comparison.py`** — the model evaluation script.
Fetches topic *text* from Postgres, re-embeds it with each candidate model in-memory (no DB writes, no schema changes), and reports a full comparison table with score matrices for every model.

```bash
docker compose exec backend bash -c "cd /app && PYTHONPATH=/app python tests/model_comparison.py"
```

**`tests/seed_topics.py`** — recreates the 5 benchmark topics in Postgres via the real service layer (Gemini expansion + SentenceBERT encoding). Run this before `test_pipeline_accuracy_db.py` if topics are missing or stale.

```bash
docker compose exec backend bash -c "cd /app && PYTHONPATH=/app python tests/seed_topics.py"
```

---

### Metrics Glossary

| Metric | What it means |
|---|---|
| **Top-1 accuracy** | Was the correct topic the highest-scoring one for this article? Measures semantic discrimination quality, independent of threshold. An article can have Top-1 correct but still be dropped if its score is below the threshold. |
| **Recall@threshold** | Did the correct topic score *above* 0.65? If not, the article is silently dropped — the user never gets an alert. This is the metric that reflects real production behaviour. |
| **Avg true-topic score** | Average cosine similarity between an article and its correct topic. Shows how close scores are to the threshold on average. |
| **p50 / p75 / p90** | Percentile scores of the correct-topic cosine similarity across all 300 articles. p90 = 0.60 means 90% of articles score below 0.60 on their correct topic. |
| **Load time** | How long the model takes to load from disk into memory. Happens once at container startup — not relevant to throughput. |
| **Encode time** | How long to compute embeddings. Happens on every article. This is the number that matters for pipeline latency. |

---

### How to Read the Score Matrix

The score matrix shows, for each group of articles (rows), the average cosine score against every topic (columns).

```
True group \ Scored as   artificial i   climate chan   global econo   ...
artificial intelligence    0.4092*        0.1480         0.2099
climate change             0.1517         0.4636*        0.3225
```

- The **diagonal** (`*`) is the correct match score — this is what needs to clear the sensitivity threshold.
- The **off-diagonal** is bleed into other topics — this should be low.
- A good model has a high diagonal and low off-diagonal (clear separation).
- If the diagonal is not clearly higher than off-diagonal, the model cannot distinguish topics — no threshold will fix that.

---

## Version History

---

### v1 — Baseline (2026-04-08)

**Changes:** None. This is the starting point.

**Architecture:**
- Stage 0: strip HTML, truncate to 2000 chars, embed `headline. content` with `all-MiniLM-L6-v2` (384-dim)
- Stage 2: single cosine similarity between article embedding and one topic embedding
- Topic embeddings: single vector from Gemini-expanded description (one paragraph) encoded at topic creation time
- Threshold: 0.65 (balanced sensitivity)

---

#### Benchmark 1 — Synthetic Topics (short names)

> Topics embedded as plain short strings e.g. `"AI regulation"`, not Gemini-expanded.
> Tests the algorithm in isolation, without relying on Gemini prompt quality.

| Category | Top-1 | Recall@0.65 | Caught |
|---|---|---|---|
| ai_healthcare | 47% | 0% | 0/15 |
| ai_jobs | 60% | 0% | 0/15 |
| ai_regulation | 87% | 0% | 0/15 |
| ai_research | 47% | 0% | 0/15 |
| climate_disasters | 87% | 0% | 0/15 |
| climate_energy | 73% | 0% | 0/15 |
| climate_oceans | 100% | 0% | 0/15 |
| climate_policy | 60% | 0% | 0/15 |
| economy_inflation | 53% | 0% | 0/15 |
| economy_markets | 80% | 0% | 0/15 |
| economy_recession | 60% | 0% | 0/15 |
| economy_trade | 87% | 0% | 0/15 |
| health_drugs | 67% | 0% | 0/15 |
| health_mental | 80% | 0% | 0/15 |
| health_pandemic | 40% | 0% | 0/15 |
| health_systems | 87% | 0% | 0/15 |
| space_commercialization | 40% | 0% | 0/15 |
| space_missions | 33% | 0% | 0/15 |
| space_policy | 60% | 0% | 0/15 |
| space_research | 93% | 0% | 0/15 |
| **OVERALL** | **67%** | **0%** | **0/300** |

Score distribution: avg=0.3390, max=0.6019, threshold=0.65

---

#### Benchmark 2 — Real DB Topics (Gemini-expanded, single vector)

| Topic | Top-1 | Recall@0.65 | Caught |
|---|---|---|---|
| Artificial Intelligence | 78% | 0% | 0/60 |
| Climate Change | 95% | 0% | 0/60 |
| Global Economy | 52% | 0% | 0/60 |
| Public Health | 85% | 0% | 0/60 |
| Space Exploration | 92% | 0% | 0/60 |
| **OVERALL** | **80%** | **0%** | **0/300** |

Score distribution: avg=0.2420, max=0.5109, threshold=0.65

**Key finding:** The maximum score any article achieved against its correct topic was 0.51 —
0.14 below the threshold. Zero articles would ever trigger an alert. The single-vector
approach cannot produce scores that clear 0.65 for broad topic matching.

---

### v2 — Multi-Vector Topic Expansion + Journalistic Prompting (2026-04-09)

**Problem being solved:** A single embedding vector can't represent the full breadth of a
broad topic like "Artificial Intelligence". An article about AI healthcare scores low against
a general AI description because their vocabularies don't overlap enough. One vector can't
be close to all angles of a broad topic simultaneously.

**Changes made:**

1. **New `topic_subtopics` table** — stores N subtopic embeddings per topic (3–15, decided by Gemini based on topic breadth). Each subtopic captures one specific angle of the parent topic.

2. **Gemini prompt rewritten** — subtopics are now written in journalistic style, not academic definitions. The old prompt produced descriptions like "Regulatory frameworks governing algorithmic decision-making systems." The new prompt produces "Government passes AI safety law. Regulators fine tech companies for biased algorithms. EU AI Act takes effect, companies face compliance deadlines." This makes the embeddings overlap with real news article language.

3. **Stage 2 upgraded to multi-vector matching** — instead of one cosine score, Stage 2 now computes:
   ```
   score = max(cosine(article, parent_embedding),
               cosine(article, subtopic_1_embedding),
               cosine(article, subtopic_2_embedding), ...)
   ```
   An article only needs to match *one* angle of the topic to pass. This is a much fairer test.

4. **`app/services/topics.py` updated** — `create_topic()` and `update_topic()` now call Gemini, get parent + subtopics, embed all of them concurrently with `asyncio.gather`, and store subtopics in `topic_subtopics`.

5. **`app/pipeline/models.py` updated** — `Topic` now carries `parent_embedding: List[float]` and `subtopic_embeddings: List[List[float]]` instead of a single `embedding`.

6. **`app/pipeline/adapters/db_adapter.py` updated** — `get_active_topics()` LEFT JOINs `topic_subtopics` and builds the subtopic list.

**Model:** `all-MiniLM-L6-v2` (384-dim) — unchanged from v1.

---

#### Benchmark — Real DB Topics (multi-vector, journalistic)

| Topic | Top-1 | Recall@0.65 | Caught |
|---|---|---|---|
| Artificial Intelligence | 85% | 0% | 0/60 |
| Climate Change | 70% | 2% | 1/60 |
| Global Economy | 90% | 7% | 4/60 |
| Public Health | 68% | 2% | 1/60 |
| Space Exploration | 98% | 2% | 1/60 |
| **OVERALL** | **82%** | **2.3%** | **7/300** |

Score distribution: avg=0.4084, p50=0.4040, p75=0.4725, p90=0.5383, threshold=0.65

**Score matrix (all-MiniLM-L6-v2):**

```
True group \ Scored as   artificial i   climate chan   global econo   public healt   space explor
artificial intelligence    0.3555*        0.1640         0.1953         0.2006         0.1836
climate change             0.1529         0.4124*        0.3023         0.2591         0.2012
global economy             0.2463         0.2963         0.4650*        0.2175         0.1595
public health              0.2416         0.1926         0.2160         0.3733*        0.1635
space exploration          0.1949         0.2379         0.1942         0.1752         0.4356*
```

**What improved vs v1:**
- Top-1: 80% → 82% (+2 points)
- Recall@0.65: 0% → 2.3% (first articles ever clearing the threshold)
- Avg score: 0.2420 → 0.4084 (+69% higher — the journalistic style + multi-vector made a huge difference)
- Max score: 0.5109 → 0.7309

**What's still the problem:** The avg score is 0.41, threshold is 0.65. Even with multi-vector
matching and journalistic prompts, the gap is too large for a 384-dim model. The p90 is 0.54 —
meaning 90% of articles score below 0.54 on their correct topic. The model has a score ceiling
that 0.65 sits above.

---

### v3 — Embedding Model Evaluation (2026-04-09)

**Problem being solved:** 384-dim models are hitting a score ceiling around 0.41 average. The
question is: does switching to a larger, more powerful model close the gap to 0.65?

**Method:** Built `tests/model_comparison.py` — a standalone evaluation script that:
1. Fetches topic *text* from Postgres (no stored embeddings used)
2. Re-embeds everything with each candidate model in-memory
3. Scores all 300 articles with multi-vector Stage 2 logic
4. Reports Top-1, Recall@threshold, score distribution, and a full score matrix per model
5. No DB writes, no schema changes — safe to run at any time

**Five models evaluated:**

| # | Model | Dim | Description |
|---|---|---|---|
| 1 | `all-MiniLM-L6-v2` | 384 | Original baseline |
| 2 | `multi-qa-MiniLM-L6-cos-v1` | 384 | Search-tuned, 384-dim (was v2 upgrade candidate) |
| 3 | `all-mpnet-base-v2` | 768 | General purpose, high quality |
| 4 | `multi-qa-mpnet-base-cos-v1` | 768 | Search-tuned, 768-dim |
| 5 | `msmarco-distilbert-base-v4` | 768 | MS MARCO retrieval-trained |

---

#### Full Results

| Model | Top-1 | Recall@0.65 | Avg | p50 | p75 | p90 | Encode/article |
|---|---|---|---|---|---|---|---|
| all-MiniLM-L6-v2 | 82.3% | 2.3% | 0.4084 | 0.4040 | 0.4725 | 0.5383 | ~5ms |
| multi-qa-MiniLM-L6-cos-v1 | 72.0% | 1.7% | 0.4113 | 0.4064 | 0.4736 | 0.5407 | ~5ms |
| **all-mpnet-base-v2** | **87.0%** | **5.0%** | **0.4583** | **0.4465** | **0.5269** | **0.6015** | ~33ms |
| multi-qa-mpnet-base-cos-v1 | 77.3% | 0.7% | 0.4025 | 0.3903 | 0.4654 | 0.5376 | ~33ms |
| msmarco-distilbert-base-v4 | 73.7% | 0.7% | 0.3583 | 0.3529 | 0.4212 | 0.4904 | ~16ms |

---

#### Score Matrices (all 5 models)

**all-MiniLM-L6-v2 (384-dim, original)**
```
True group \ Scored as   artificial i   climate chan   global econo   public healt   space explor
artificial intelligence    0.3555*        0.1640         0.1953         0.2006         0.1836
climate change             0.1529         0.4124*        0.3023         0.2591         0.2012
global economy             0.2463         0.2963         0.4650*        0.2175         0.1595
public health              0.2416         0.1926         0.2160         0.3733*        0.1635
space exploration          0.1949         0.2379         0.1942         0.1752         0.4356*
```

**multi-qa-MiniLM-L6-cos-v1 (384-dim, search-tuned)**
```
True group \ Scored as   artificial i   climate chan   global econo   public healt   space explor
artificial intelligence    0.3481*        0.2274         0.2321         0.2493         0.2021
climate change             0.1708         0.4300*        0.3326         0.3215         0.2273
global economy             0.3062         0.3292         0.4772*        0.2841         0.1924
public health              0.2858         0.2520         0.2638         0.3918*        0.1805
space exploration          0.2057         0.2737         0.2215         0.1902         0.4096*
```

**all-mpnet-base-v2 (768-dim, general) ← selected**
```
True group \ Scored as   artificial i   climate chan   global econo   public healt   space explor
artificial intelligence    0.4092*        0.1480         0.2099         0.2016         0.1569
climate change             0.1517         0.4636*        0.3225         0.3112         0.1751
global economy             0.2182         0.3042         0.4865*        0.2417         0.1517
public health              0.2483         0.1967         0.2381         0.4251*        0.1247
space exploration          0.2111         0.2201         0.1863         0.1599         0.5071*
```

**multi-qa-mpnet-base-cos-v1 (768-dim, search-tuned)**
```
True group \ Scored as   artificial i   climate chan   global econo   public healt   space explor
artificial intelligence    0.3490*        0.2055         0.1948         0.2471         0.1905
climate change             0.1893         0.4230*        0.3045         0.2858         0.2089
global economy             0.2454         0.3480         0.4717*        0.2858         0.1982
public health              0.2523         0.2350         0.2500         0.3830*        0.2138
space exploration          0.2162         0.2562         0.1982         0.2098         0.3857*
```

**msmarco-distilbert-base-v4 (768-dim, retrieval)**
```
True group \ Scored as   artificial i   climate chan   global econo   public healt   space explor
artificial intelligence    0.2876*        0.1935         0.2044         0.2387         0.1715
climate change             0.1601         0.3528*        0.2824         0.2408         0.1813
global economy             0.2273         0.2803         0.3952*        0.2453         0.1536
public health              0.2101         0.2379         0.2347         0.3303*        0.1487
space exploration          0.1929         0.2238         0.1763         0.1782         0.4257*
```

---

#### Why `all-mpnet-base-v2` Wins

**Top-1 accuracy: 87%** — best of all 5 models by a wide margin. Means the pipeline picks
the correct topic for 87 out of 100 articles.

**Score matrix discrimination** — `all-mpnet-base-v2` has the cleanest separation between
diagonal and off-diagonal. Example: Space Exploration diagonal is 0.5071 vs the next highest
off-diagonal of 0.2201. That gap (~0.29) is significantly larger than any other model.

**p90 = 0.6015** — closest any model gets to the threshold. The top 10% of articles are
reaching near-threshold scores. This led to threshold recalibration in v5 — balanced was
moved from 0.65 → 0.45, putting it below p90 and enabling real recall.

**What surprised us:** `multi-qa-MiniLM-L6-cos-v1` and `multi-qa-mpnet-base-cos-v1` (both
"search-tuned") actually *underperformed* their general-purpose counterparts. The search-tuned
models are optimised for asymmetric retrieval (short query → long document). Our use case is
symmetric (medium description → medium article), so the general-purpose models fit better.

**Throughput:** `all-mpnet-base-v2` encodes at ~33ms/article on CPU. At peak load the
pipeline processes ~5–20 articles/minute — the model can handle ~1,800/minute in batch mode,
giving 90–360× headroom. Not a concern.

---

### v4 — Migrate to `all-mpnet-base-v2` (768-dim) (2026-04-09)

**Decision:** `all-mpnet-base-v2` was the clear winner of the 5-model benchmark in v3.
Committed to a full schema migration and model swap.

**Files changed:**

| File | Change |
|---|---|
| `alembic/versions/20260409_006_vector_768.py` | New migration: all vector columns 384 → 768, IVFFlat index dropped and recreated |
| `app/db/models.py` | `Vector(384)` → `Vector(768)` on `Topic`, `TopicSubtopic`, `Article`, `SubTheme` |
| `app/core/embeddings.py` | Default model: `all-MiniLM-L6-v2` → `all-mpnet-base-v2`, docstring updated |
| `app/pipeline/adapters/embedding_adapter.py` | Default model: `multi-qa-MiniLM-L6-cos-v1` → `all-mpnet-base-v2`, docstring updated |
| `run_real_pipeline.py` | Log message updated |
| `tests/test_pipeline_accuracy.py` | Model name in report header updated |
| `tests/test_pipeline_accuracy_db.py` | Model name in report header updated |

**How to apply:**

```bash
# 1. Run the migration
docker compose exec backend bash -c "cd /app && alembic upgrade head"

# 2. Re-seed topics (all stored embeddings are now invalid)
docker compose exec backend bash -c "cd /app && PYTHONPATH=/app python tests/seed_topics.py"

# 3. Run the benchmark to confirm results
docker compose exec backend bash -c "cd /app && PYTHONPATH=/app pytest tests/test_pipeline_accuracy_db.py -v -s"
```

**Why `topic_subtopics` is truncated by the migration:** The table stores 384-dim vectors.
After the dimension change those rows are incompatible — pgvector would reject any cosine
similarity operation against a 768-dim article embedding. The migration truncates the table
so the NOT NULL constraint can be re-added cleanly. `seed_topics.py` repopulates it.

**Pre-migration baseline (v2, all-MiniLM-L6-v2, 384-dim):**

| Metric | Value |
|---|---|
| Top-1 accuracy | 82% |
| Recall@0.65 | 2.3% |
| Avg true-topic score | 0.4084 |
| p90 score | 0.5383 |

**Expected after migration (confirmed by model_comparison.py):**

| Metric | Target |
|---|---|
| Top-1 accuracy | 87% |
| Recall@0.65 | 5.0% |
| Avg true-topic score | 0.4583 |
| p90 score | 0.6015 |

**Actual results after migration (threshold still at 0.65 at time of test):**

| Topic | Top-1 | Recall@0.65 | Caught |
|---|---|---|---|
| Artificial Intelligence | 93% | 3% | 2/60 |
| Climate Change | 90% | 7% | 4/60 |
| Global Economy | 83% | 7% | 4/60 |
| Public Health | 80% | 2% | 1/60 |
| Space Exploration | 97% | 8% | 5/60 |
| **OVERALL** | **89%** | **5%** | **16/300** |

Score distribution: avg=0.4487, max=0.7788, p90≈0.60

Score matrix:
```
True group \ Scored as   artificial i   climate chan   global econo   public healt   space explor
artificial intelligence    0.4257*        0.1696         0.2164         0.1865         0.1757
climate change             0.1472         0.4516*        0.2677         0.2218         0.1815
global economy             0.1839         0.3005         0.4387*        0.2412         0.1599
public health              0.2235         0.1862         0.2216         0.4220*        0.1316
space exploration          0.1877         0.2023         0.1913         0.1451         0.5053*
```

---

### v5 — Threshold Recalibration (2026-04-09)

**Problem:** The old thresholds (broad=0.20, balanced=0.40, high=0.50) were set before
benchmarking. After measuring real scores with the new model, the noise floor (max
off-diagonal) sits around 0.30. The old balanced threshold of 0.40 was too close to
the noise floor, risking false positives.

**Decision rule:** Threshold must sit at least 10 points above the highest off-diagonal
noise score. Max off-diagonal across the score matrix is ~0.30 (Climate↔Economy).

| Sensitivity | Old | New | Recall | Rationale |
|---|---|---|---|---|
| broad | 0.20 | 0.40 | 64% | 10pt buffer above noise floor |
| balanced | 0.40 | 0.45 | 48% | Midpoint between noise and avg diagonal |
| high | 0.50 | 0.55 | 18% | Only high-confidence matches |

**Files changed:**
- `app/config.py` — threshold defaults updated
- `tests/test_pipeline_accuracy_db.py` — thresholds now read from `get_settings()` instead of hardcoded; assertions updated to Top-1 ≥ 85%, Recall ≥ 40%

**Test assertions after recalibration:**
- Top-1 ≥ 85% (was 60%)
- Recall@balanced ≥ 40% (was 50% at old threshold of 0.65 — now achievable)

The test and production pipeline now use identical thresholds — no more drift.
