# Discovery Pipeline Architecture & Optimization

This document details the architecture of the sub-theme discovery pipeline and the rationale behind the accuracy improvements implemented to solve "narrative drift" and "noise contamination."

---

## 1. High-Level Pipeline Flow

1.  **Extraction**: All news articles within the rolling window (default 3 days) for a topic are fetched.
2.  **Projection (UMAP)**: 768-dimensional embeddings are reduced to **10 dimensions** (optimized).
3.  **Clustering (HDBSCAN)**: Dense groups are identified using **Leaf** mode for maximum granularity.
4.  **Identity Resolution**: Each new cluster proposes a match from the DB using **85% Centroid Similarity**.
5.  **Conflict Resolution (Loser-Merge)**: If multiple clusters match the same ID, they are merged into one.
6.  **Persistence**: Snapshots are saved. Noise members (<60% similarity) are kicked out. Centroids are **frozen** to prevent drift.

---

## 2. Parameter Rationale (The "180 IQ" Settings)

### UMAP: 5 → 10 Components
- **Problem**: 5 dimensions were too compressed. Articles semantically different in 768D (e.g., Trump Shooting vs. India Cops) were being forced into the same 5D neighborhood.
- **Solution**: 10 dimensions preserve significantly more local semantic structure while still being efficient for HDBSCAN.
- **Result**: Drastically reduces "accidental" clustering of unrelated articles.

### HDBSCAN: EOM → Leaf
- **Problem**: EOM (Excess of Mass) tries to find "broad" clusters, which often leads to merging distinct but related sub-stories into one blob.
- **Solution**: Leaf mode forces the algorithm to pick the most granular, tightest clusters possible.
- **Stability**: Since we have a robust **Identity Match** logic (85%), if Leaf over-splits a story, the pipeline simply merges them back together in Step 5.

### Frozen Centroids
- **Problem**: Updating the centroid every run allowed the narrative to "drift." Over time, a "Trump Shooting" story could slowly morph into "US Gun Laws" without the system noticing.
- **Solution**: The centroid is now set only once (at birth). All future runs are measured against the original "First Principles" center.
- **Result**: If the story evolves too far, it will simply fail to match the old centroid and correctly spawn a **new** sub-theme (e.g., "Trump Shooter Trial").

### 60% Membership Guard
- **Problem**: HDBSCAN (operating in 10D) sometimes includes edge-case articles.
- **Solution**: A final sanity check in 768D.
- **Rule**: Any article with `< 0.60` similarity to the centroid is excluded from the sub-theme during persistence.

---

## 3. Relabeling & Volume Baseline

We moved from a "snapshot-to-snapshot" growth check to a **Label-Time Baseline**.

- **Old Logic**: If volume grows 15% in Run 1 and 15% in Run 2, the 30% relabeling trigger is never hit.
- **New Logic**: We store `volume_at_last_label`. We only relabel if current volume is **>50%** (configurable) higher than the volume that was present when the current label was generated.
- **Benefit**: Prevents "label churn" and ensures AI only re-analyzes a story when significant new signal has arrived.

---

## 4. Conflict Resolution: Loser-Merge

When two different clusters (A and B) both match an existing Sub-Theme (ID 123) with ≥85% similarity:
1.  The one with the **highest similarity** wins the ID.
2.  The "loser" cluster is **absorbed** into the winner.
3.  Their article lists and Reddit counts are merged before saving.
4.  This prevents the creation of "Ghost" sub-themes that are essentially duplicates of existing ones.

---

## 5. Current Production Config (Admin Panel)

| Parameter | Value | Rationale |
|---|---|---|
| `n_components` | 10 | Sweet spot for semantic preservation. |
| `cluster_selection` | leaf | Granularity first; merge second. |
| `centroid_match` | 0.85 | High bar for narrative identity. |
| `member_min_sim` | 0.60 | Post-clustering noise filter. |
| `relabel_spike` | 0.50 | 50% growth required to trigger AI. |
