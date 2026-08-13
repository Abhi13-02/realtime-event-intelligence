"""
Unit tests for sub-theme identity scoring.

The thresholds asserted here are calibrated against measurements in
docs/discovery-accuracy-log.md v2, produced by tests/benchmark_identity_stability.py:

    same story, window fully rotated : mean 0.790, min 0.703
    different stories, same topic   : mean 0.444, max 0.803

Those two distributions OVERLAP, which is the whole reason identity moved off
centroid cosine and onto article overlap. These tests pin that behaviour so it
cannot quietly regress back to a cosine-only matcher.

Run:
    docker compose exec backend python -m pytest tests/test_identity_matching.py -v
"""
import pytest

from app.tasks.discovery.labeling import _jaccard, identity_score

JACCARD_MATCH = 0.30    # subtheme_jaccard_match_threshold
CENTROID_MATCH = 0.85   # subtheme_centroid_match_threshold
DRIFT_FLOOR = 0.60      # subtheme_drift_floor


def score(jaccard, cosine):
    return identity_score(
        jaccard=jaccard,
        cosine=cosine,
        jaccard_threshold=JACCARD_MATCH,
        centroid_threshold=CENTROID_MATCH,
        drift_floor=DRIFT_FLOOR,
    )


class TestJaccard:
    def test_identical_sets(self):
        assert _jaccard({1, 2, 3}, {1, 2, 3}) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({1, 2}, {3, 4}) == 0.0

    def test_partial_overlap(self):
        # 2 shared, 4 total
        assert _jaccard({1, 2, 3}, {2, 3, 4}) == pytest.approx(0.5)

    def test_empty_is_not_a_match(self):
        # A dormant sub-theme has no members. It must not score as a perfect
        # match against another empty cluster.
        assert _jaccard(set(), set()) == 0.0
        assert _jaccard({1}, set()) == 0.0


class TestIdentityScore:
    def test_high_overlap_wins_even_when_centroid_has_drifted(self):
        # THE CORE FIX. A story reported with fresh articles drifts to ~0.79
        # against its frozen centroid — under the 0.85 the old matcher required,
        # so it was declared new and its original was sunsetted. Article overlap
        # keeps it attached.
        assert score(jaccard=0.92, cosine=0.79) > 0

    def test_full_window_turnover_still_matches_via_overlap(self):
        # Consecutive real runs share ~92% of the window; even a heavily rotated
        # one stays well above the Jaccard threshold.
        assert score(jaccard=0.35, cosine=0.80) > 0

    def test_overlap_always_outranks_cosine_only(self):
        # Shared articles are direct evidence; a similar centroid is
        # circumstantial. Tiering, not a weighted sum.
        assert score(jaccard=0.31, cosine=0.61) > score(jaccard=0.0, cosine=0.99)

    def test_stronger_overlap_scores_higher(self):
        assert score(jaccard=0.90, cosine=0.80) > score(jaccard=0.40, cosine=0.80)

    def test_cosine_fallback_when_no_membership_history(self):
        # A revived narrative has no members from last run, so overlap is 0 and
        # cosine is the only signal available.
        assert score(jaccard=0.0, cosine=0.90) == pytest.approx(0.90)

    def test_cosine_fallback_is_strict_enough_to_avoid_false_merges(self):
        # Different stories in the same topic peak at 0.803 in the benchmark, so
        # anything at or below that must NOT match on cosine alone.
        assert score(jaccard=0.0, cosine=0.803) == 0.0
        assert score(jaccard=0.0, cosine=0.84) == 0.0

    def test_weak_overlap_and_weak_cosine_is_no_match(self):
        assert score(jaccard=0.10, cosine=0.70) == 0.0

    @pytest.mark.parametrize("jaccard", [0.0, 0.5, 1.0])
    def test_drift_veto_overrides_any_overlap(self, jaccard):
        # The stored centroid never moves, so it is a permanent record of what
        # the narrative was at birth. Falling below the floor means it has
        # become something else — fork it regardless of shared articles. This is
        # what stops a chain of high-overlap runs walking one story into another.
        assert score(jaccard=jaccard, cosine=0.55) == 0.0

    def test_drift_floor_never_fires_on_a_healthy_rotated_story(self):
        # Benchmark minimum for a same-story full turnover is 0.703; the floor
        # sits at 0.60 so ordinary rotation never trips it.
        assert score(jaccard=0.50, cosine=0.703) > 0

    def test_drift_floor_still_fires_on_a_genuinely_different_story(self):
        # Different-story mean is 0.444, comfortably under the floor.
        assert score(jaccard=0.50, cosine=0.444) == 0.0

    @pytest.mark.parametrize(
        "jaccard,cosine",
        [(0.30, 0.60), (0.30, 0.85), (1.00, 1.00)],
    )
    def test_threshold_boundaries_are_inclusive(self, jaccard, cosine):
        assert score(jaccard, cosine) > 0

    def test_scores_are_ordered_across_tiers(self):
        # Every overlap-tier score must exceed every cosine-tier score, so the
        # Hungarian assignment never prefers circumstantial evidence.
        overlap_tier = [score(j, 0.80) for j in (0.30, 0.60, 1.00)]
        cosine_tier = [score(0.0, c) for c in (0.85, 0.95, 1.00)]
        assert min(overlap_tier) > max(cosine_tier)
