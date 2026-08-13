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
docker compose exec backend bash -c "cd /app && PYTHONPATH=/app python tests/benchmark_discovery_accuracy.py"
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

---

### v2 — Identity stability measured for the first time (2026-08-14)

**No clustering config changed.** This entry adds a benchmark that measures
something v1 never did, and the result overturns how sub-theme identity is
matched.

**What was missing:** every number in v1 is *cross-sectional* — at one moment,
are two different sub-themes distinguishable? But `subtheme_centroid_match_threshold`
governs a *longitudinal* question: as the rolling window turns over, does the
**same** story's centroid stay within the threshold of its own frozen centroid?
That number had never been measured. 0.85 was chosen by feel.

**New harness:** `tests/benchmark_identity_stability.py`. For each ground-truth
sub-category it builds two equal windows and slides them apart, so overlap runs
from "the window has not moved" to "every article has been replaced".

**Results** (window = 7 articles, threshold under test = 0.85):

| Articles shared | Jaccard | Centroid cosine (mean) | min | max | Identity lost |
|---|---|---|---|---|---|
| 7 | 1.00 | 1.000 | 1.000 | 1.000 | 0/20 (0%) |
| 5 | 0.56 | 0.939 | 0.911 | 0.961 | 0/20 (0%) |
| 3 | 0.27 | 0.881 | 0.794 | 0.912 | 4/20 (20%) |
| 1 | 0.08 | 0.823 | 0.755 | 0.873 | 17/20 (85%) |
| 0 | 0.00 | **0.790** | 0.703 | 0.844 | **20/20 (100%)** |

Different stories in the same topic: mean **0.444**, max **0.803** (n=30).

**The finding:**

1. **At 0.85 every story loses its identity once its window fully rotates.**
   Not some — all twenty. It is then recreated as a new sub-theme and the
   original is sunsetted to zero volume. On the dashboard that reads as a
   narrative dying with a near-duplicate appearing beside it, and the dead one
   is the ghost card that used to 404 when clicked.

2. **The mechanism is the frozen centroid, not run-to-run variation.** With
   `subtheme_window_days=3` and a 6-hour interval, consecutive runs share ~92%
   of their articles — comfortably inside the safe band. But the stored centroid
   is frozen at creation and never moves, so after ~3 days it is being compared
   against a cluster that shares none of its original articles.

3. **No cosine threshold can fix this.** Same-story-after-turnover averages
   0.790; different-story tops out at 0.803. The distributions **overlap** —
   separation is −0.013. Raise the threshold and healthy stories are lost;
   lower it and genuinely different stories merge. Centroid similarity alone
   cannot carry identity, at any setting.

4. **Membership overlap tracks identity cleanly where cosine does not.** Jaccard
   falls monotonically with rotation and is unambiguous in exactly the region
   real consecutive runs occupy.

**What changed as a result** (see Phase 4 in the identity-resolution work):

- Membership overlap against the previous run becomes the primary signal.
- Frozen-centroid cosine stays at **0.85** but only as a fallback for when no
  membership history exists — deliberately conservative, since 0.85 sits above
  the different-story maximum of 0.803 and so cannot cause a false merge.
- The drift veto uses **0.60** against the immutable first centroid. That sits
  below the healthy-story minimum after full turnover (0.703) so it never fires
  on a story that is merely being reported with fresh articles, and above the
  different-story mean (0.444) so it still fires when a narrative has genuinely
  become something else. The cross-story *maximum* of 0.803 does not affect this
  choice: the veto only ever splits, never merges.

---

### v3 — Clustering is chaotically sensitive; embeddings left unnormalised (2026-08-14)

**An attempted improvement was measured, found harmful, and reverted.** The
finding underneath it is more important than the change.

**What was tried:** `normalize_embeddings=True` on both encoders. Rationale:
sub-theme centroids are an unweighted mean, so vectors with unequal norms tilt
the mean toward longer documents. Every comparison in the codebase is cosine,
which is scale-invariant, so this looked free.

**What it actually did** (window geometry as v1: `min_cluster_size=3`,
`min_samples=2`, `n_components=5`):

| Topic | Clusters unnorm → norm | Purity | Recall |
|---|---|---|---|
| Climate Change | 7 → 2 | 92% → 50% | 100% → 25% |
| Artificial Intelligence | 6 → 2 | 79% → 64% | 100% → 25% |
| Global Economy | 3 → 2 | 73% → 64% | 50% → 25% |
| Public Health | 6 → 6 | 87% → 80% | 50% → 50% |
| Space Exploration | 3 → 3 | 61% → 61% | 50% → 50% |

**Why that is not a result about normalisation:**

- Normalised and unnormalised vectors point in the **same direction** to
  1.49e-08. Normalising is idempotent with the unit-scaling the cosine
  functions already apply.
- Batch and per-text encoding produce **bit-identical** vectors (max diff 0.0).
- Clustering is **deterministic** — the same input twice gives the same answer.

So a **1.5e-08 perturbation** reproducibly flips a topic from 7 clusters at 100%
recall to 2 clusters at 25%. Article ordering flips it too. **UMAP + HDBSCAN at
n=60 sits on a knife edge**, and any input change large enough to exist at all
can reshape the output.

**Consequences worth acting on:**

1. **The benchmark numbers are not stable to rebuilds.** `requirements.txt` pins
   **0 of 32** packages. The image rebuilt on 2026-08-14 carries umap 0.5.12,
   scikit-learn 1.9.0, numpy 2.5.2, sentence-transformers 5.7.0 — none of which
   are necessarily what produced v1 in April. After reverting normalisation,
   four of five topics returned to their exact v1 values; Public Health did not
   (v1: 4 clusters/84%/50%, now: 2/47%/0%), and unpinned dependency drift on a
   chaotic pipeline is the most likely cause. **Pinning these versions is the
   single highest-value change for making this benchmark mean anything.**

2. **Small-sample instability is a property of the current config**, not a bug
   in any one change. Real topics carry more than 60 articles, which should
   help, but the config has never been validated for stability.

3. **This does NOT affect the v2 identity measurements.** Those compute
   centroids directly from ground-truth categories and never invoke
   UMAP/HDBSCAN, so they are unaffected by this sensitivity. The Phase 4 A/B
   below is also unaffected: both arms run identical clustering and differ only
   in the matcher.

**Decision:** embeddings stay **unnormalised**. The change had a theoretical
rationale, no measurable benefit, and a real cost in perturbing a sensitive
pipeline. Both encoders carry a comment so it is not "fixed" again.

**Phase 4 identity matcher — controlled A/B**, same real articles
(`climate_energy`), same clustering, 7-article window stepping 2 per run over
5 runs so run 5 shares nothing with run 1. The only difference is the matcher:

| | cosine-only (old) | overlap + drift veto (new) |
|---|---|---|
| sub-themes that held the story | **2** | **1** |
| ghost (dormant) clusters left | **1** | **0** |
| total sub-themes for 2 stories | **3** | **2** |

The old matcher lost the story at run 4 and sunsetted the original to zero
volume — reproducing the reported ghost-cluster bug exactly. The new matcher
held one identity across the full turnover.
