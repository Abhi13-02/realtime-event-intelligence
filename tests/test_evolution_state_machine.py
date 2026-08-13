"""
Unit tests for the narrative state machine.

These cover the two pure functions extracted in the Phase 1 refactor:
classify_status() and derive_events(). Neither touches a database, which is the
whole point — the rules that decide what a user sees on the dashboard should be
provable without standing up Postgres, Kafka and a Celery worker.

Run:
    docker compose exec backend python -m pytest tests/test_evolution_state_machine.py -v
    # or locally, with the app package importable:
    python -m pytest tests/test_evolution_state_machine.py -v
"""
import pytest

from app.tasks.discovery.evolution import (
    EVENT_DISAPPEARING,
    EVENT_EMERGING,
    EVENT_GROWING,
    STATUS_DECLINING,
    STATUS_DORMANT,
    STATUS_GROWING,
    STATUS_NEW,
    STATUS_REJECTED,
    STATUS_REVIVAL,
    STATUS_STEADY,
    classify_status,
    derive_events,
)

GROW = 0.20
DECLINE = 0.20


def classify(prev, curr):
    """Shorthand with the production default thresholds."""
    return classify_status(prev, curr, grow_threshold=GROW, decline_threshold=DECLINE)


# ── classify_status ──────────────────────────────────────────────────────────

class TestClassifyStatus:
    def test_first_ever_snapshot_is_new_with_no_percentage(self):
        # There is no baseline, so any percentage would be invented. This is the
        # bug that used to render a 7-article revival as "+700%".
        assert classify(None, 12) == (STATUS_NEW, None)

    def test_brand_new_but_empty_cluster_is_dormant_not_new(self):
        # HDBSCAN can group a cluster whose members are then all removed by the
        # similarity guard. Calling that 'new' would put an empty card on the
        # live dashboard, so emptiness wins over novelty.
        assert classify(None, 0) == (STATUS_DORMANT, None)

    def test_zero_volume_is_dormant(self):
        status, growth = classify(40, 0)
        assert status == STATUS_DORMANT
        assert growth == pytest.approx(-1.0)

    def test_dormant_stays_dormant_without_a_percentage(self):
        # 0 -> 0 has no meaningful delta; -100% would be a lie.
        assert classify(0, 0) == (STATUS_DORMANT, None)

    def test_return_from_zero_is_revival(self):
        # Percentage against a zero baseline is undefined, so the STATE carries
        # the meaning instead of a fabricated number.
        assert classify(0, 9) == (STATUS_REVIVAL, None)

    def test_growth_above_threshold(self):
        status, growth = classify(10, 15)
        assert status == STATUS_GROWING
        assert growth == pytest.approx(0.5)

    def test_decline_below_threshold(self):
        status, growth = classify(20, 10)
        assert status == STATUS_DECLINING
        assert growth == pytest.approx(-0.5)

    def test_small_movement_is_steady_in_both_directions(self):
        up_status, up_growth = classify(100, 110)
        down_status, down_growth = classify(100, 90)
        assert up_status == STATUS_STEADY
        assert down_status == STATUS_STEADY
        assert up_growth == pytest.approx(0.10)
        assert down_growth == pytest.approx(-0.10)

    def test_no_change_is_steady_at_zero_percent(self):
        assert classify(30, 30) == (STATUS_STEADY, pytest.approx(0.0))

    @pytest.mark.parametrize(
        "prev,curr,expected",
        [
            (100, 120, STATUS_GROWING),      # exactly +20% — boundary is inclusive
            (100, 119, STATUS_STEADY),       # just under
            (100, 80, STATUS_DECLINING),     # exactly -20% — boundary is inclusive
            (100, 81, STATUS_STEADY),        # just above
        ],
    )
    def test_threshold_boundaries_are_inclusive(self, prev, curr, expected):
        assert classify(prev, curr)[0] == expected

    def test_declining_status_never_reports_positive_growth(self):
        # The regression this whole phase exists to prevent: status and the
        # percentage shown next to it are now derived from the same number, so
        # they cannot contradict each other.
        for prev in range(1, 60):
            for curr in range(0, 60):
                status, growth = classify(prev, curr)
                if status == STATUS_DECLINING:
                    assert growth is not None and growth < 0
                if status == STATUS_GROWING:
                    assert growth is not None and growth > 0

    def test_custom_thresholds_are_respected(self):
        # Zero decline threshold means any drop at all reads as declining.
        status, _ = classify_status(100, 99, grow_threshold=0.5, decline_threshold=0.0)
        assert status == STATUS_DECLINING


# ── derive_events ────────────────────────────────────────────────────────────

class TestDeriveEvents:
    def test_first_sighting_emits_emerging(self):
        assert derive_events(None, STATUS_NEW) == [EVENT_EMERGING]

    def test_first_sighting_of_an_empty_cluster_emits_nothing(self):
        assert derive_events(None, STATUS_DORMANT) == []

    def test_going_dormant_emits_disappearing(self):
        assert derive_events(STATUS_DECLINING, STATUS_DORMANT) == [EVENT_DISAPPEARING]

    def test_revival_emits_emerging(self):
        # Reuses the existing alert_type so intelligence_alerts needs no migration.
        assert derive_events(STATUS_DORMANT, STATUS_REVIVAL) == [EVENT_EMERGING]

    def test_starting_to_grow_emits_growing(self):
        assert derive_events(STATUS_STEADY, STATUS_GROWING) == [EVENT_GROWING]

    def test_sustained_growth_only_alerts_once(self):
        # The old code re-fired sub_theme_growing every run, to every subscribed
        # user, for as long as the story kept growing.
        assert derive_events(STATUS_GROWING, STATUS_GROWING) == []

    def test_sustained_dormancy_does_not_re_alert(self):
        assert derive_events(STATUS_DORMANT, STATUS_DORMANT) == []

    def test_decline_is_not_an_alert(self):
        # Visible on the dashboard as a chip, but not worth waking someone up.
        assert derive_events(STATUS_STEADY, STATUS_DECLINING) == []

    def test_rejected_never_alerts(self):
        assert derive_events(STATUS_STEADY, STATUS_REJECTED) == []
        assert derive_events(None, STATUS_REJECTED) == []

    def test_events_are_never_contradictory(self):
        # The old implementation ran independent threshold checks, so a cluster
        # could emit growing AND disappearing in the same run.
        all_statuses = [
            STATUS_NEW, STATUS_GROWING, STATUS_STEADY,
            STATUS_DECLINING, STATUS_DORMANT, STATUS_REVIVAL, STATUS_REJECTED,
        ]
        for prev in [None] + all_statuses:
            for curr in all_statuses:
                events = derive_events(prev, curr)
                assert len(events) <= 1, f"{prev} -> {curr} produced {events}"
                assert not (EVENT_GROWING in events and EVENT_DISAPPEARING in events)


# ── the two together ─────────────────────────────────────────────────────────

class TestLifecycle:
    def test_a_full_narrative_lifecycle(self):
        """Walk one story from birth to death and confirm each step reads right."""
        timeline = [
            # (prev_volume, volume, expected_status, expected_events)
            (None, 8,  STATUS_NEW,       [EVENT_EMERGING]),
            (8,    22, STATUS_GROWING,   [EVENT_GROWING]),
            (22,   30, STATUS_GROWING,   []),                     # still growing, no re-alert
            (30,   31, STATUS_STEADY,    []),
            (31,   18, STATUS_DECLINING, []),
            (18,   0,  STATUS_DORMANT,   [EVENT_DISAPPEARING]),
            (0,    5,  STATUS_REVIVAL,   [EVENT_EMERGING]),
        ]

        prev_status = None
        for prev_volume, volume, expected_status, expected_events in timeline:
            status, _ = classify(prev_volume, volume)
            events = derive_events(prev_status, status)
            assert status == expected_status, f"vol {prev_volume}->{volume}"
            assert events == expected_events, f"vol {prev_volume}->{volume}"
            prev_status = status
