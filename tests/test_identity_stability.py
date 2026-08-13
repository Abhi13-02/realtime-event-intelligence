"""
Identity Stability Benchmark — does a story stay recognisable as itself?

WHY THIS EXISTS
===============
test_discovery_accuracy.py measures a CROSS-SECTIONAL question: at one moment,
are two different sub-themes distinguishable? Its published numbers are
inter-cluster centroid similarity 0.40-0.54 and intra-cluster article similarity
0.32-0.41 (see docs/discovery-accuracy-log.md).

Nothing has ever measured the LONGITUDINAL question, which is the only one the
identity threshold actually governs: as the rolling window turns over, does the
SAME story's centroid stay within subtheme_centroid_match_threshold of itself?

That matters because the stored centroid is frozen at creation — it is the mean
of whichever articles happened to be in the window on the run where the cluster
first appeared. The window then rolls and those articles age out. If drift
exceeds the threshold, the story is declared brand new: a duplicate sub-theme is
created and the original is sunsetted to zero volume. On the dashboard that
looks like a narrative dying and an near-identical one being born beside it —
and the dead one is exactly the ghost card that used to 404 when clicked.

WHAT IT MEASURES
================
For each ground-truth sub-category, it builds two overlapping windows of equal
size and varies how many articles they share, simulating the window rolling
forward. At each overlap level it reports:

  * centroid cosine  — what the current frozen-centroid matcher relies on
  * Jaccard overlap  — what membership-based matching would rely on
  * how many stories would LOSE their identity at the configured threshold

The cross-story baseline (different sub-categories, same topic) is reported
alongside, because a threshold is only safe if it sits comfortably between
"same story next run" and "a genuinely different story".

HOW TO RUN
==========
  docker compose exec backend bash -c \
    "cd /app && PYTHONPATH=/app python tests/test_identity_stability.py"
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from app.pipeline.adapters.embedding_adapter import SentenceBertAdapter
from app.tasks.discovery.models import _cosine_similarity

DATASET_PATH = Path(__file__).parent / "testDataset.tsv"

# Half of each 15-article sub-category, so two windows of this size can be
# slid apart far enough to share nothing at all.
WINDOW = 7

# Articles shared between window A and window B. 7 = the window has not moved;
# 0 = every article has been replaced.
OVERLAP_LEVELS = [7, 5, 3, 1, 0]

parser = argparse.ArgumentParser()
parser.add_argument(
    "--threshold",
    type=float,
    default=0.85,
    help="subtheme_centroid_match_threshold to evaluate (default: production 0.85)",
)
ARGS = parser.parse_args()


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]*>", "", text)


def load_dataset() -> dict[str, list[str]]:
    """sub_category -> [text, ...]"""
    by_cat: dict[str, list[str]] = defaultdict(list)
    with DATASET_PATH.open(encoding="utf-8") as fh:
        for row in csv.reader(fh, delimiter="\t"):
            if len(row) < 5:
                continue
            _id, _src, sub_category, headline, body = row[:5]
            by_cat[sub_category].append(strip_html(f"{headline}. {body}"))
    return by_cat


def centroid(vecs: list[np.ndarray]) -> np.ndarray:
    return np.array(vecs).mean(axis=0)


def jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def main() -> None:
    if not DATASET_PATH.exists():
        print(f"Dataset not found at {DATASET_PATH}")
        sys.exit(1)

    print("Loading embedding model (all-mpnet-base-v2)...")
    embedder = SentenceBertAdapter()
    by_cat = load_dataset()

    # Embed once; every measurement below is a re-slicing of these vectors.
    print(f"Embedding {sum(len(v) for v in by_cat.values())} articles...")
    vecs_by_cat = {
        cat: [np.array(embedder.encode_text(t)) for t in texts]
        for cat, texts in by_cat.items()
    }

    topic_of = lambda cat: cat.split("_")[0]  # noqa: E731

    # ── same story, window rolled forward ────────────────────────────────
    results: dict[int, list[float]] = defaultdict(list)
    jaccards: dict[int, list[float]] = defaultdict(list)

    for cat, vecs in vecs_by_cat.items():
        if len(vecs) < WINDOW * 2:
            continue
        idx_a = set(range(WINDOW))
        vec_a = [vecs[i] for i in idx_a]
        c_a = centroid(vec_a)

        for overlap in OVERLAP_LEVELS:
            shift = WINDOW - overlap
            idx_b = set(range(shift, shift + WINDOW))
            if max(idx_b) >= len(vecs):
                continue
            c_b = centroid([vecs[i] for i in idx_b])
            results[overlap].append(_cosine_similarity(c_a, c_b))
            jaccards[overlap].append(jaccard(idx_a, idx_b))

    # ── different stories within the same topic ──────────────────────────
    cross: list[float] = []
    cats = list(vecs_by_cat)
    for i, a in enumerate(cats):
        for b in cats[i + 1:]:
            if topic_of(a) != topic_of(b):
                continue
            cross.append(
                _cosine_similarity(
                    centroid(vecs_by_cat[a][:WINDOW]),
                    centroid(vecs_by_cat[b][:WINDOW]),
                )
            )

    # ── report ───────────────────────────────────────────────────────────
    th = ARGS.threshold
    print()
    print("=" * 74)
    print("  IDENTITY STABILITY  ·  same story, window rolling forward")
    print(f"  window size {WINDOW} articles · threshold under test {th:.2f}")
    print("=" * 74)
    print()
    print(f"  {'shared':>6}  {'jaccard':>8}  {'centroid cosine':>26}  {'lost identity':>14}")
    print(f"  {'':>6}  {'':>8}  {'mean':>8} {'min':>8} {'max':>8}  {'':>14}")
    print("  " + "-" * 70)

    worst_safe_overlap = None
    for overlap in OVERLAP_LEVELS:
        sims = results.get(overlap)
        if not sims:
            continue
        arr = np.array(sims)
        lost = int((arr < th).sum())
        jac = float(np.mean(jaccards[overlap]))
        flag = "" if lost == 0 else "  <-- breaks"
        print(
            f"  {overlap:>6}  {jac:>8.2f}  {arr.mean():>8.3f} {arr.min():>8.3f} "
            f"{arr.max():>8.3f}  {lost:>3}/{len(arr):<3} ({lost / len(arr):.0%}){flag}"
        )
        if lost == 0:
            worst_safe_overlap = overlap

    cross_arr = np.array(cross) if cross else np.array([0.0])
    print()
    print(f"  Different stories, same topic : mean {cross_arr.mean():.3f}  "
          f"max {cross_arr.max():.3f}  (n={len(cross_arr)})")
    print()

    # ── interpretation ───────────────────────────────────────────────────
    all_sims = np.concatenate([np.array(v) for v in results.values()]) if results else np.array([])
    full_turnover = np.array(results.get(0, [0.0]))

    print("  READING")
    print("  " + "-" * 70)
    print(f"  A same-story centroid holds above {th:.2f} only while the window still")
    if worst_safe_overlap is not None:
        print(f"  shares at least {worst_safe_overlap}/{WINDOW} of its articles "
              f"({worst_safe_overlap / WINDOW:.0%} overlap).")
    else:
        print("  shares ALL of its articles — it breaks at the very first rotation.")
    print()
    print(f"  After a FULL turnover the same story scores {full_turnover.mean():.3f} on average,")
    print(f"  while a genuinely different story scores {cross_arr.mean():.3f}.")

    margin = full_turnover.mean() - cross_arr.max()
    print(f"  Separation between those two cases: {margin:+.3f}")
    print()
    if full_turnover.mean() < th:
        print(f"  => At {th:.2f} the matcher LOSES a story once its window turns over,")
        print("     even though that story is still far more similar to itself than")
        print("     to any other story. It gets recreated as new and the original is")
        print("     sunsetted — the ghost-cluster failure mode.")
    else:
        print(f"  => At {th:.2f} the matcher survives a full window turnover.")
    print()

    # A drift floor must sit BELOW where the same story lands after complete
    # turnover (or it fires on healthy stories) and ABOVE where different
    # stories land (or it never fires at all).
    lo, hi = cross_arr.max(), full_turnover.mean()
    print("  DRIFT FLOOR (Phase 4 veto against the immutable first centroid)")
    print("  " + "-" * 70)
    if hi > lo:
        suggested = round(lo + (hi - lo) / 2, 2)
        print(f"  Must exceed {lo:.3f} (highest different-story score) and stay under")
        print(f"  {hi:.3f} (same story after full turnover).")
        print(f"  Midpoint suggestion: {suggested:.2f}")
    else:
        print("  No safe gap on this dataset — same-story-after-turnover overlaps")
        print("  different-story scores. Membership overlap must carry identity.")
    print()
    print("=" * 74)


if __name__ == "__main__":
    main()
