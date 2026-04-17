# Discovery Accuracy Log

This document tracks the accuracy of the sub-theme discovery worker over time.
Every time the clustering config, embedding model, or discovery logic changes,
a new entry is added here with benchmark results and what changed.

---

## How the Benchmark Works

### Ground Truth

The discovery worker is unsupervised — it finds clusters in the embedding space
with no pre-defined labels. To measure its accuracy, we use the 300-article TSV
dataset (`tests/testDataset.tsv`) which has a second level of labels: 20 sub-categories
(4 per topic, 15 articles each). These sub-categories are exactly the kind of
sub-themes the discovery worker should organically find.

```
Artificial Intelligence  → ai_regulation, ai_healthcare, ai_jobs, ai_research
Climate Change           → climate_policy, climate_oceans, climate_energy, climate_disasters
Global Economy           → economy_trade, economy_recession, economy_markets, economy_inflation
Space Exploration        → space_research, space_policy, space_missions, space_commercialization
Public Health            → health_systems, health_pandemic, health_mental, health_drugs
```

For each topic:
1. Embed all 60 articles with the real production model
2. Run `_step1_cluster()` — the same HDBSCAN+UMAP function used in production
3. Compare cluster assignments to sub-category labels

### Limitations

- This is a **synthetic benchmark** — real discovery runs on live articles crawled
  from RSS/Reddit/HN. Article quality, volume, and diversity will differ.
- The TSV dataset has exactly 15 articles per sub-category. Real sub-themes may have
  uneven distributions, or new sub-themes may emerge that don't map to any TSV label.
- HDBSCAN is non-deterministic unless `random_state` is fixed (it is — set to 42 in
  the UMAP step). Results are reproducible across runs with the same data.

### How to Run

```bash
docker compose exec backend bash -c "cd /app && PYTHONPATH=/app python tests/test_discovery_accuracy.py"
```

---

## Metrics Glossary

| Metric | What it means |
|---|---|
| **Cluster count** | How many sub-themes HDBSCAN found. Ideally close to 4 per topic (one per sub-category). Too few = over-merging. Too many = over-splitting. |
| **Noise ratio** | % of articles HDBSCAN rejected as noise (could not assign to any cluster). High noise = parameters too strict or not enough data per cluster. |
| **Cluster purity** | For each cluster, the % of its articles that share the same sub-category. High purity = clusters are semantically clean. Avg across all clusters per topic. |
| **Sub-category recall** | % of sub-categories that dominate at least one cluster (>50% of a cluster's members). A sub-category is "missed" if its articles were scattered across clusters or fell into noise. |
| **Silhouette score** | Overall cluster quality. Range [-1, 1]. >0.3 = reasonable separation. >0.5 = strong structure. Computed on original 768-dim embeddings with cosine distance. Skipped if fewer than 2 clusters. |
| **Intra-cluster similarity** | Average cosine similarity between articles within the same cluster. Higher = tighter, more coherent clusters. |
| **Inter-cluster similarity** | Average cosine similarity between cluster centroids. Lower = better separation between sub-themes. |

### How to Read the Sub-Category → Cluster Mapping

```
Sub-category           Best cluster   Members   Recalled
--------------------   ------------   -------   --------
ai_regulation          Cluster 0      12/15     ✓
ai_healthcare          Cluster 1      11/15     ✓
ai_jobs                Cluster 2       9/15     ✓
ai_research            noise           8/15     ✗ (missed)
```

- **Best cluster**: the cluster where most of this sub-category's articles ended up
- **Members**: how many of the 15 articles landed in that cluster vs total in sub-category
- **Recalled ✓**: the sub-category dominated that cluster (>50% of cluster members)
- **Missed ✗**: articles were scattered or fell into noise — discovery would not produce a clean sub-theme for this sub-category

---

## Version History

---

### v1 — Baseline (2026-04-09)

**No changes — this is the starting point.**

**Config:**
- Model: `all-mpnet-base-v2` (768-dim)
- `min_cluster_size`: 3
- `min_samples`: 2
- UMAP: `n_components`=5, `n_neighbors`=15, `min_dist`=0.0, `metric`=cosine

**Results:**

| Topic | Clusters | Noise | Purity | Recall | Silhouette | Intra | Inter |
|---|---|---|---|---|---|---|---|
| Artificial Intelligence | 6 | 13% | 79% | 100% | 0.076 | 0.322 | 0.405 |
| Climate Change | 5 | 5% | 91% | 100% | 0.132 | 0.356 | 0.421 |
| Global Economy | 2 | 2% | 67% | 25% | 0.151 | 0.321 | 0.535 |
| Public Health | 4 | 7% | 84% | 50% | 0.102 | 0.360 | 0.427 |
| Space Exploration | 3 | 0% | 61% | 50% | 0.167 | 0.408 | 0.510 |
| **OVERALL** | | **5%** | **76%** | **65%** | **0.126** | | |

**Sub-category → cluster mapping:**

```
Artificial Intelligence
  ai_healthcare    → Cluster 3  (15/15)  ✓
  ai_jobs          → noise       (6/15)  ✓  (dominated cluster despite noise)
  ai_regulation    → Cluster 0   (7/15)  ✓
  ai_research      → Cluster 5  (10/15)  ✓

Climate Change
  climate_disasters → Cluster 3  (10/15)  ✓
  climate_energy    → Cluster 2  (14/15)  ✓
  climate_oceans    → Cluster 4  (14/15)  ✓
  climate_policy    → Cluster 0   (6/15)  ✓

Global Economy
  economy_inflation  → Cluster 0  (15/15)  ✗  merged with recession + markets
  economy_markets    → Cluster 0  (14/15)  ✗  merged
  economy_recession  → Cluster 0  (15/15)  ✗  merged
  economy_trade      → Cluster 1  (15/15)  ✓

Public Health
  health_drugs     → Cluster 0  (12/15)  ✗  merged with pandemic
  health_mental    → Cluster 1  (10/15)  ✓
  health_pandemic  → Cluster 0  (14/15)  ✗  merged with drugs
  health_systems   → Cluster 3  (13/15)  ✓

Space Exploration
  space_commercialization → Cluster 2  (15/15)  ✗  merged with policy
  space_missions          → Cluster 0   (8/15)  ✓
  space_policy            → Cluster 2  (15/15)  ✗  merged with commercialization
  space_research          → Cluster 1  (10/15)  ✓
```

**Key findings:**

**What works well:**
- **Climate Change** is the strongest performer — 91% purity, 100% recall, all 4 sub-categories cleanly separated. The sub-categories (disasters, energy, oceans, policy) have distinct enough vocabulary that HDBSCAN finds them naturally.
- **Artificial Intelligence** achieves 100% recall despite over-splitting (6 clusters instead of 4). All sub-categories have at least one cluster dominated by them — the model finds the right groups, just sometimes splits them further.
- **Noise is low overall (5%)** — articles are generally dense enough for HDBSCAN to assign them.

**What doesn't work well:**
- **Global Economy is the weakest (25% recall)** — inflation, recession, and markets all merged into one large cluster. These sub-categories share too much financial vocabulary (GDP, interest rates, market indices) for the model to separate them. Only trade has distinct enough signal to stand alone.
- **Space Exploration merges commercialization and policy** — both involve business/government language around space, making them hard to distinguish semantically.
- **Public Health merges drugs and pandemic** — both involve medical treatment, pharmaceutical companies, and public health responses.

**What the silhouette scores tell us:**
- All silhouette scores are low (0.07–0.17). This means clusters exist but are not sharply separated — articles from different sub-categories have similar embeddings. This is expected: within a broad topic like "Global Economy", all articles share vocabulary even when covering different angles.
- Low silhouette ≠ bad clustering. The discovery worker's job is to surface *relative* groupings within a topic, not to find perfectly distinct clusters. Climate Change with silhouette=0.13 still achieves 100% recall.

**Inter vs intra similarity:**
- Intra (within cluster): 0.32–0.41 — articles within a cluster are moderately similar
- Inter (between centroids): 0.40–0.54 — cluster centroids are only slightly less similar to each other than within clusters. The gap is small, which explains low silhouette scores.
- Global Economy has the highest inter-cluster similarity (0.535) and lowest recall — its sub-categories are the hardest to pull apart semantically.
